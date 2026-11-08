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

## Customer cloud contract under development

Customer code will create a WorldFoundry client with a **WorldFoundry API key**:

```python
import os
from worldfoundry import WorldFoundry

wf = WorldFoundry(api_key=os.environ["WORLDFOUNDRY_API_KEY"])
projects = wf.projects.list()
```

Source code now defaults to the WorldFoundry gateway. This code is **not yet
available in the published 0.2.0 package**. The gateway deployment has not
passed its production configuration and authenticated end-to-end verification,
so do not use this example as a live onboarding instruction yet.

WorldFoundry owns one internal Supabase project for identity, database records,
private traces, and key verifiers. Customer code must not need its provider
URL, publishable key, service credential, or user access token. The full
customer/company contract is in
[`customer-company-boundary.md`](customer-company-boundary.md).

Cloud `training.run_local(...)` will run simulations and user code on the
customer's computer and sync results. It is not managed hosted Python
execution. Hosted workers, trusted metering, and Stripe billing remain
separate release gates.

