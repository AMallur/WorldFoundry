# WorldFoundry hosted simulation runtime (beta)

The published Python SDK connects to the WorldFoundry gateway with a WorldFoundry
API key. The gateway authenticates requests and accesses company-owned Supabase
resources. Do not put Supabase admin credentials, project management tokens, or
database passwords in the public SDK.

The runtime provides hosted state, environment actions, scheduled scenario
events, deterministic evaluation, and persistent event history. It does not
execute arbitrary customer Python or perform production-system writes. A
customer agent runs on the customer's own computer/server and calls WorldFoundry.

## Register a configurable environment

POST /v1/environments with this body:

~~~json
{
  "project_id": "PROJECT_UUID",
  "name": "order-system",
  "initial_state": {
    "orders": {"O-1": {"status": "pending", "notes": [], "retry_count": 0}}
  },
  "instruction": "Resolve order O-1 and record a note",
  "actions": {
    "resolve_order": {
      "operation": "set",
      "path": "orders.$order_id.status",
      "value": "resolved",
      "parameters": {"order_id": {"type": "string"}}
    },
    "add_note": {
      "operation": "append",
      "path": "orders.$order_id.notes",
      "from_param": "note",
      "parameters": {
        "order_id": {"type": "string"},
        "note": {"type": "string"}
      }
    }
  }
}
~~~

POST /v1/scenarios with this body:

~~~json
{
  "project_id": "PROJECT_UUID",
  "name": "order-exception",
  "checks": [
    {"name": "resolved", "path": "orders.O-1.status", "equals": "resolved"},
    {"name": "reviewed", "path": "orders.O-1.notes", "equals": ["reviewed"]}
  ],
  "events": [
    {
      "at_step": 2,
      "operation": "increment",
      "path": "orders.O-1.retry_count",
      "value": 1
    }
  ]
}
~~~

The declarative actions supported are read, set, append and increment.
Parameter placeholders begin with a dollar sign. Paths must exist in the
initial state. Configurations are validated when starting a session.
Event operations use literal paths.

## Use from the Python SDK

~~~python
import os
from worldfoundry import WorldFoundry

wf = WorldFoundry(api_key=os.environ["WORLDFOUNDRY_API_KEY"])
session = wf.simulations.start(
    project_id="PROJECT_UUID",
    environment_id="ENVIRONMENT_UUID",
    scenario_id="SCENARIO_UUID",
)
step = wf.simulations.act(
    session["id"], "resolve_order",
    expected_version=session["version"],
    parameters={"order_id": "O-1"},
)
step = wf.simulations.act(
    session["id"], "add_note",
    expected_version=step["version"],
    parameters={"order_id": "O-1", "note": "reviewed"},
)
result = wf.simulations.submit(session["id"], expected_version=step["version"])
print(result["score"], result["checks"])
print(wf.simulations.events(session["id"]))
~~~

This client interface will be available after the new version is published
to PyPI. Updating GitHub does not publish the Python distribution.

## Durability and access control

- The wf_sim_sessions table contains the current state and version.
- The wf_sim_events table records immutable actions and results.
- The wf_sim_commit RPC uses a row lock, version check and call ID to
  reject conflicts and prevent duplicate transitions.
- Every customer operation checks project ownership or a scoped API key.
- Supabase RLS is enabled and direct user access to these tables is revoked.
- State is limited to 64 KiB and sessions to 1,000 action steps.
- The API has a soft limit of 100 active sessions per project. Stronger
  atomic quotas and infrastructure rate limits are needed for public launch.

## Deployment checklist

1. Review and apply the hosted_simulation_runtime SQL migration to the
   company-owned Supabase project after staging tests.
2. Redeploy the worldfoundry-customer-api Edge Function with BOTH index.ts
   and runtime.ts. Keep the existing server-side credentials and gateway.
3. Verify account login, API keys, and one-company-cannot-read-another tests
   against the live API.
4. Publish the next SDK release using GitHub Actions / PyPI Trusted Publishing.
5. Add monitoring, backup/recovery exercises and load tests before making an SLA.

This release is hosted environment execution, NOT cloud execution of arbitrary
customer agents. A later sandboxed worker and queue will be needed for that,
with audited egress restrictions and verified compute metering.
