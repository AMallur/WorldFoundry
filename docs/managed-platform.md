# WorldFoundry managed platform v0.5

WorldFoundry provides a customer-facing PyPI SDK and authenticated HTTPS API.
Internal services manage persistence, compute, billing and extensions. Never
embed Supabase service-role credentials, Stripe secrets, worker tokens, or
Google service account credentials in customer code or Git history.

## Repository packages

- src/worldfoundry/ — Public Python SDK
- backend/api/ — Private Cloud Run worker and separate public Stripe webhook API
- backend/orchestration/ — Cloud Tasks task creation, delivery and dispatch
- backend/core/ — Server-only Supabase PostgREST and Storage adapter
- backend/billing/ — Stripe Checkout, signature-checked webhooks, usage reporting
- backend/provisioning/ — Default customer entitlements
- backend/connectors/ — Read-only application snapshot adapter
- runtime/ — Deterministic stateful simulation, scenario events, grading, replay
- supabase/migrations/ — Tenant-protected data storage and admission functions
- supabase/functions/ — API key and organization authorization at the gateway
- infrastructure/ — Docker, Cloud Build, Terraform, Cloud Tasks config

## Current executable managed workload

The managed service executes **declarative scripted plans**: sequences of
validated read/set/append/increment actions against a simulated JSON state.
It DOES NOT run arbitrary uploaded Python, LLM agents, or live production
connectors. Scenario events can inject changes and graded checks evaluate
each final state. Edge-scripted mode executes up to 5 episodes / 40 steps
synchronously. Cloud Tasks mode (up to 100 episodes / 100 steps) requires a
deployed private worker and dispatcher and is OFF by default.

The default quota is 20 reserved episodes per project per UTC calendar month.
The Supabase admission SQL serializes concurrent reservations per project.

## Customer SDK example (0.5.0)

    import os
    from worldfoundry import WorldFoundry
    wf = WorldFoundry(api_key=os.environ["WORLDFOUNDRY_API_KEY"])
    project = wf.projects.create(name="Demo")
    env = wf.environments.create(
        project_id=project["id"], name="Order system",
        initial_state={"order": {"status": "open"}},
        actions={"close": {"operation": "set", "path": "order.status",
                           "value": "closed"}},
    )
    scenario = wf.scenarios.create(
        project_id=project["id"], name="Resolve",
        checks=[{"name": "closed", "path": "order.status", "equals": "closed"}],
    )
    agent = wf.agents.create(
        project_id=project["id"], name="Scripted baseline",
        plan=[{"action": "close", "parameters": {}}],
    )
    run = wf.managed_runs.create(
        project_id=project["id"], environment_id=env["id"],
        scenario_id=scenario["id"], agent_id=agent["id"], episodes=2,
    )
    print(run, wf.managed_runs.episodes(run["id"]))
    print(wf.billing.entitlement(project["id"]))

Datasets: wf.artifacts.upload_dataset(project_id=..., path="snapshot.json")
(max 512 KiB inline); wf.artifacts.list(project_id) returns metadata.
wf.artifacts.download_url(artifact_id) returns a 60-second signed private URL.

## Supabase deployment

Apply the managed_run_services SQL migration against the WorldFoundry Supabase
project. Redeploy index.ts, runtime.ts and managed.ts **together** as the existing
WorldFoundry customer API. The function implements WorldFoundry authentication
and requires the private gateway token; there is no customer Supabase credential.
Managed tables have RLS enabled and reject direct anon/authenticated access.
Each customer resource operation is additionally scoped to owned project IDs.

## Google Cloud Run / Cloud Tasks deployment

1. Select a GCP project and enable Cloud Run, Cloud Tasks, Cloud Build,
   Artifact Registry, Secret Manager APIs; create a Docker repository.
2. Build the worker Docker image using
   infrastructure/cloud-run/cloudbuild.yaml with a specific _IMAGE target.
3. Create Secret Manager secrets named wf-supabase-service-role and
   wf-worker-token and inject their values securely (not Terraform state).
4. Set the variables in infrastructure/terraform/ and run terraform plan,
   then apply. This creates an IAM-protected Cloud Run worker, queue, service
   accounts and limited worker scaling. Review IAM before deployment.
5. Deploy a private scheduled Cloud Run Job using the same image with command
   python -m backend.orchestration.dispatcher and the environment in
   infrastructure/cloud-tasks/config.example.env. Grant its service account
   Secret Manager access and Cloud Tasks enqueue permissions. Schedule it
   periodically or run manually when jobs are queued.
6. Verify OIDC authenticated tasks, retries, tenant-scoped storage, quotas,
   and actual worker completion before setting WF_CLOUD_EXECUTION_ENABLED=true
   on the Supabase Edge Function.

No Google Cloud project was connected or provisioned by these code changes.

## Stripe billing deployment

Choose the Stripe account to use. Do not configure an unrelated Stripe account
or enable live billing by accident. Configure STRIPE_SECRET_KEY,
STRIPE_WEBHOOK_SECRET, STRIPE_PRICE_ID, and fixed callback URLs in a separate
public Cloud Run billing service built with Dockerfile.billing. Its webhook
verifies Stripe-Signature; its checkout route requires WF_BILLING_SHARED_TOKEN
forwarded from WorldFoundry's authenticated API. Link
WF_BILLING_SERVICE_URL in the Edge Function only after deployment.

The backend supports per-project Stripe customer mapping, checkout,
subscription lifecycle updates and trusted meter-event reporting. Meters must
be configured with a matching event name, value and customer mapping. Do not
turn on charges or metering until testing with a selected Stripe test account
and confirming plan/pricing policies.

## Limits

- Live onboarding/multi-tenant smoke tests, retry recovery, disaster recovery,
  larger dataset transfer and load testing remain necessary.
- Generated scripts can be used for simulations but arbitrary customer code
  requires isolated execution sandboxes and network/secret protections.
- No AI model is trained or weights updated by these runs; the SDK exposes
  repeatable experience data for separate agent training systems.
