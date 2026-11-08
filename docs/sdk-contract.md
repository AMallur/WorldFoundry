# WorldFoundry SDK contract and deployment boundary

## Working locally

The `worldfoundry` distribution installs the `worldfoundry` import and CLI. The SDK runs
on the user's computer and uses a local resource registry plus the existing episode engine.

```python
from worldfoundry import WorldFoundry

def agent(task, tools):
    tools.set_priority(ticket_id="TCK-100", priority="critical")
    tools.assign(ticket_id="TCK-100", assignee="on-call")
    tools.reply(ticket_id="TCK-100", message="We acknowledge the outage and opened an incident.")
    tools.resolve(ticket_id="TCK-100")
    tools.submit()

wf = WorldFoundry.local(".wf-data")
env = wf.environments.create(template="customer_support", difficulty="beginner")
registered = wf.agents.register(name="support", handler=agent)
run = wf.training.create(agent=registered, environment=env, episodes=10, seed=42)
print(run.summary, run.report_path)
```

Local resource managers presently include `projects`, `environments`, `agents`, `scenarios`,
`datasets`, `policies`, and `feedback`. Generic resource managers persist metadata, but only the
built-in support desk environment, Python callable agents, and sequential batch execution are
executable. A local agent registration's callable exists only in its Python process; the metadata
record is persistent, but the handler must be registered again after restart. `max_steps` is
enforced. `concurrency=1` is currently required. Advanced difficulty and remote endpoint agents
are rejected explicitly. `report_path` is a local JSON file; no hosted report URL is fabricated.

The lower-level `start`, `act`, `submit`, `export_trace`, REST, and CLI episode APIs remain usable.

## Cloud client boundary

`WorldFoundry(api_key="SUPABASE_USER_ACCESS_TOKEN", base_url="https://<ref>.supabase.co/functions/v1/worldfoundry-api")` constructs an
authenticated HTTP client. The token is a signed-in user's Supabase access token, not a project
publishable key or a service-role key. It sends `/v1/projects`, `/v1/environments`, `/v1/agents`,
`/v1/scenarios`, `/v1/datasets`, `/v1/training-runs`, and `/v1/episodes` requests. The cloud
client is a transport contract, not a deployed service. A Supabase database alone cannot execute
arbitrary Python agents or isolated simulation workers; it needs a WorldFoundry API and runner.

The project `bhvffruseefvifjcutzj` has the schema applied and the `worldfoundry-api` Edge Function
deployed at `https://bhvffruseefvifjcutzj.supabase.co/functions/v1/worldfoundry-api`. The API
authenticates Supabase user access tokens and performs project-scoped database operations through
row level security. A publishable key alone is not a user session.

```python
from worldfoundry.cloud import CloudWorldFoundry

wf = CloudWorldFoundry.sign_in(
    project_url="https://bhvffruseefvifjcutzj.supabase.co",
    publishable_key="<the project's publishable key>",
    email="<your signed-up email>",
    password="<your password>",
)
project = wf.projects.create(name="My agent lab")
environment = wf.environments.create(
    project_id=project["id"], name="Support desk", template="support-desk"
)
agent = wf.agents.register(
    project_id=project["id"], name="Support agent", framework="python"
)
result = wf.training.run_local(
    project_id=project["id"], agent=agent, environment=environment,
    handler=my_agent, episodes=10,
)
print(result["summary"])
```

`run_local` executes the agent and simulations on the user's computer, then records episode scores
and private JSONL traces in the Supabase project. It does not offer managed remote execution.
The cloud API creates run records but has no hosted Python worker attached, so bare
`wf.training.create(...)` leaves a queued run until a runner processes it. The deployed endpoint
is live; signed-in end-to-end execution still needs a user account and session for verification.

For managed execution, add a durable queue, isolated Python workers, trace artifact storage,
worker authentication, and report generation. Store provider secrets in a managed secret service;
never put raw secrets in run traces or resource config.

