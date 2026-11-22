# WorldFoundry: what code to use for what

**Applies to:** Python package `worldfoundry==0.8.0` (Python 3.11–3.13).  
**Source of truth:** [the actual SDK code](../src/worldfoundry/) and [packaging metadata](../pyproject.toml).  
**Status:** Local SDK examples below are implemented; hosted customer onboarding and managed-compute/billing readiness remain incomplete. The hosted runtime uses declarative state, not arbitrary uploaded Python or direct model-weight training.

This guide starts with the **task a developer wants to accomplish**, then shows the appropriate code and what it does. It intentionally separates customer-facing code from backend implementation files.

## 1. Which code should I use?

| I want to… | Use this | Runs where? |
| --- | --- | --- |
| Try the idea without setup | [One-click demo](https://worldfoundry-demo.vercel.app/) | Browser; scripted demonstration |
| Install the developer toolkit | `pip install worldfoundry==0.8.0` | Developer computer |
| See available environments | `worldfoundry environments list` | Local |
| Run one task manually | `wf.start()`, `wf.act()`, `wf.submit()` | Local |
| Run a simulation from the terminal | `worldfoundry episodes start/act/submit` | Local |
| Define a simulation without coding a Python class | `wf.environments.create(template="declarative", config=...)` | Local |
| Import a JSON environment | `worldfoundry environments import FILE` | Local |
| Implement custom tools and business logic | `EnvironmentPlugin` / `wf.environments.register_template()` | Trusted local Python |
| Connect an existing Python agent | `wf.agents.register(handler=...)` | Local |
| Execute repeated attempts and grade them | `wf.training.create(...)` | Local |
| Create variations, inject events, and grade special cases | `wf.scenarios.register_generator()` / scenario JSON | Local |
| Export an action history | `wf.export_trace(episode_id, "trace.jsonl")` | Local |
| Connect an MCP-capable agent | `python -m worldfoundry.integrations.mcp` | Local stdio |
| Wrap tool calls for Google ADK | `worldfoundry.integrations.adk.tools` | Local |
| Execute a standalone Meta ARE scenario | `MetaARERunner` | Separate Meta ARE runtime |
| Store/version project resources in the hosted library | `WorldFoundry.cloud(...)`, `wf.templates`, `wf.environments` | WorldFoundry API / Supabase; authenticated account required |
| Run stateful hosted JSON simulations | `wf.simulations.start/act/submit` | Hosted declarative runtime; authenticated account required |
| Compare simulation rules with recorded outcomes | `ReferenceCase`, `verify_reference_cases` | Experimental local reality SDK |
| Analyze existing OTLP or Debezium data | `otlp_span_events`, `debezium_row_changes`, `directly_follows` | Offline local analysis |

## 2. The six concepts that matter

- **Environment:** The simulated application/system, including **state** and the **actions** allowed. Example: a customer-support desk with tickets.
- **Scenario:** A particular task, initial-state overrides, unexpected events, and success checks. Example: resolve a high-priority outage.
- **Agent:** The code/AI that chooses actions in the environment. WorldFoundry does not supply or automatically train an LLM.
- **Episode:** One run of one task; has its own state, status and trace. Example: attempt number 1.
- **Action:** A permitted state transition or read. Example: `assign` or `resolve`.
- **Evaluation/trace:** The final checks/score and a step-by-step account of what the agent did.

A **training run** can create several episodes and summarize their results. WorldFoundry produces experiences, scores and traces. **It does not update model weights**; use a separate learning pipeline if you want the agent to learn from that data.

## 3. Install and choose a mode

~~~bash
python -m pip install worldfoundry==0.8.0
worldfoundry --version
~~~

The `wf` terminal command is an alias for `worldfoundry`.

**Local mode — no account required:**

~~~python
from worldfoundry import WorldFoundry
wf = WorldFoundry.local(".wf-data")
~~~

The `".wf-data"` path stores episodes/resources on your own computer. `WorldFoundry(".wf-data")` is also supported.

**Cloud mode — WorldFoundry API key required:**

~~~python
import os
from worldfoundry import WorldFoundry
wf = WorldFoundry.cloud(api_key=os.environ["WORLDFOUNDRY_API_KEY"])
~~~

This connects to the WorldFoundry HTTPS service, **not directly to the developer's Supabase instance**. As of v0.8.0, live customer key issuance/onboarding and production isolation still require verification. Do not assume this code will work without a properly provisioned account/key. Do not place API keys in source control.

## 4. Run one existing simulation (local Python)

~~~python
from worldfoundry import WorldFoundry

wf = WorldFoundry.local(".wf-data")
episode = wf.start("support-desk", task="incident-triage", seed=7)

print(episode.id)           # Unique ID for this attempt
print(episode.instruction)  # The task the agent should complete

# One action at a time changes the simulated episode state.
ticket = wf.act(episode.id, "get_ticket", ticket_id="TCK-100")
print(ticket.observation)

wf.act(episode.id, "set_priority", ticket_id="TCK-100", priority="critical")
wf.act(episode.id, "assign", ticket_id="TCK-100", assignee="on-call")
wf.act(episode.id, "reply", ticket_id="TCK-100",
       message="We acknowledge the outage and opened an incident.")
wf.act(episode.id, "resolve", ticket_id="TCK-100")

result = wf.submit(episode.id)
print(result.passed, result.score, result.to_dict()["checks"])

wf.export_trace(episode.id, "trace.jsonl")
~~~

**What each call does:**

| Code | Effect |
| --- | --- |
| `wf.start(environment, task, seed)` | Creates a fresh isolated episode and initial state. `seed` makes configured variations reproducible. |
| `wf.available_actions(episode.id)` | Shows names of tools available in this episode. |
| `wf.act(id, name, **parameters)` | Validates arguments, runs one simulated action, commits state and returns a `StepResult` with an `observation`. |
| `wf.get(id)` | Retrieves state, instruction, status and validation information for an episode. |
| `wf.submit(id)` | Checks final state against grading rules; returns `ValidationResult` (`passed`, `score`, `checks`). Submission ends the episode. |
| `wf.export_trace(id, path)` | Writes JSONL events describing the episode, successful/failed actions and evaluation. |
| `wf.list_episodes()` | Lists stored local episodes. |

Source: [`engine.py`](../src/worldfoundry/engine.py), [`models.py`](../src/worldfoundry/models.py), [runnable example](../examples/python_episode.py).

### The same workflow from the CLI

~~~bash
export WORLDFOUNDRY_HOME="$PWD/.wf-data"
worldfoundry environments list
worldfoundry episodes start support-desk --task incident-triage --seed 7
# Copy the printed episode ID:
EPISODE_ID=ep_replace_me

worldfoundry episodes inspect "$EPISODE_ID"
worldfoundry episodes act "$EPISODE_ID" get_ticket --params '{"ticket_id":"TCK-100"}'
worldfoundry episodes act "$EPISODE_ID" set_priority --params '{"ticket_id":"TCK-100","priority":"critical"}'
worldfoundry episodes act "$EPISODE_ID" assign --params '{"ticket_id":"TCK-100","assignee":"on-call"}'
worldfoundry episodes act "$EPISODE_ID" reply --params '{"ticket_id":"TCK-100","message":"We acknowledge the outage and opened an incident."}'
worldfoundry episodes act "$EPISODE_ID" resolve --params '{"ticket_id":"TCK-100"}'
worldfoundry episodes submit "$EPISODE_ID"
worldfoundry traces export "$EPISODE_ID" --output trace.jsonl
~~~

For an API rather than terminal/Python, start `worldfoundry serve --port 8787` and use the local `/v1/episodes` endpoints. See [the curl example](../examples/curl_episode.sh). The local REST server is not the hosted customer API.

## 5. Build your own environment with JSON (no Python environment class)

Use `declarative` when your world can be modeled as JSON state and four actions:

| Operation | Meaning |
| --- | --- |
| `read` | Return a value without changing state |
| `set` | Replace a value |
| `append` | Add an item to a list |
| `increment` | Increase a numeric value |

Example: a warehouse order simulator.

~~~python
from worldfoundry import WorldFoundry

wf = WorldFoundry.local(".wf-data")
warehouse = wf.environments.create(
    template="declarative",
    name="Warehouse",
    config={
        "instruction": "Inspect and ship the order.",
        "initial_state": {"order": {"status": "pending", "verified": False}},
        "actions": {
            "inspect": {"operation": "read", "path": "order.status"},
            "verify": {"operation": "set", "path": "order.verified", "value": True},
            "ship": {"operation": "set", "path": "order.status", "value": "shipped"}
        },
        "checks": [
            {"name": "verified", "path": "order.verified", "equals": True},
            {"name": "shipped", "path": "order.status", "equals": "shipped"}
        ]
    },
)

episode = wf.start(warehouse.id)
wf.act(episode.id, "inspect")
wf.act(episode.id, "verify")
wf.act(episode.id, "ship")
print(wf.submit(episode.id).to_dict())
~~~

- `initial_state`: JSON data the simulated system starts with.
- `actions`: named operations an agent may invoke; these are its tools.
- `instruction`: task shown to the agent.
- `checks`: exact conditions used to score success.

You can also save the definition as JSON and import it:

~~~bash
worldfoundry environments import examples/warehouse.environment.json
~~~

See [the complete warehouse JSON](../examples/warehouse.environment.json) and [the declarative interpreter](../src/worldfoundry/declarative.py). **This does not call a real warehouse system.**

### Scenario vs environment: when to use which

Keep system behavior in the **environment**. Put task-specific variations in the **scenario**:

~~~python
scenario = {
    "instruction": "Ship order O1 after checking it.",
    "state_overrides": {"orders": {"O1": {"status": "held"}}},
    "events": [
        {"at_step": 2, "operation": "set",
         "path": "orders.O1.status", "value": "delayed"}
    ],
    "checks": [
        {"name": "shipped", "path": "orders.O1.status", "equals": "shipped"}
    ]
}
~~~

Pass the scenario as `wf.start(environment_id, scenario=scenario)` **only when the referenced paths already exist in that environment**. At successful action step 2, the event modifies the state; submission checks the final outcome. Alternatively, register seed-driven scenario generators for repeated local runs: `wf.scenarios.register_generator(name, function)`. See [custom environments](custom-environments.md).

## 6. Connect an existing Python agent and run many episodes

You do not need to create the agent inside WorldFoundry. Provide a callable that takes a task instruction and an object exposing the environment's tools:

~~~python
from worldfoundry import WorldFoundry

def support_agent(instruction, tools):
    tools.get_ticket(ticket_id="TCK-100")
    tools.set_priority(ticket_id="TCK-100", priority="critical")
    tools.assign(ticket_id="TCK-100", assignee="on-call")
    tools.reply(ticket_id="TCK-100",
                message="We acknowledge the outage and opened an incident.")
    tools.resolve(ticket_id="TCK-100")
    tools.submit()

wf = WorldFoundry.local(".wf-data")
environment = wf.environments.create(template="customer_support")
agent = wf.agents.register(name="support-agent", handler=support_agent)
run = wf.training.create(agent=agent, environment=environment,
                         episodes=10, seed=42)

print(run.summary)      # Episode count, mean score, success rate
print(run.report_path)  # JSON report saved on this computer
~~~

**Where your code goes:** `support_agent` is the developer's agent implementation/adapter. The `tools` object routes calls into a WorldFoundry environment. `training.create` runs episodes sequentially and aggregates results; it is not an RL trainer. In this local release, `concurrency=1` is required. Registered Python handlers live in the process and must be re-registered after restart.

See [runnable batch example](../examples/sdk_training.py) and [`platform.py`](../src/worldfoundry/platform.py).

## 7. When JSON is not enough: a Python environment plugin

Choose a plugin when actions require custom Python logic or multiple coordinated state changes.

Implement an environment with these methods:

| Method/property | Responsibility |
| --- | --- |
| `id`, `name`, `description`, `tasks`, `instruction` | Identity and the task shown to the agent |
| `initial_state(seed)` | Build a new JSON-serializable state |
| `actions()` | Publish tool names, descriptions and parameter schemas as `ActionSpec` |
| `perform(state, action, parameters)` | Validate and perform a stateful tool call; return an observation |
| `validate(state)` | Return `ValidationResult` with named `ValidationCheck` entries |
| `register(wf)` | Register the local template through `wf.environments.register_template(...)` |

Start with the fully implemented [counter plugin](../examples/custom_counter_template.py). Load trusted code explicitly:

~~~python
wf = WorldFoundry.local(".wf-data",
    plugins=["examples.custom_counter_template"])
env = wf.environments.create(template="counting", config={"target": 11})
~~~

Or for the CLI:

~~~bash
worldfoundry --plugin examples.custom_counter_template environments list
~~~

Plugin code runs **locally in the developer's process**, not in the shared hosted service. For third-party data, `wf.connectors.register("orders", connector)` accepts an explicitly provided object with `snapshot()`; each episode uses its own snapshot, not production writes. See [custom-environments.md](custom-environments.md).

## 8. Hosted resource library — save definitions centrally

**Requires a valid WorldFoundry account/API key.** The SDK contains the following interfaces, but onboarding and live authorization checks are not yet complete.

~~~python
import os
from worldfoundry import WorldFoundry

wf = WorldFoundry.cloud(api_key=os.environ["WORLDFOUNDRY_API_KEY"])
project = wf.projects.create(name="Operations lab")

template = wf.templates.create(
    project_id=project["id"], name="Warehouse",
    config={
        "initial_state": {"order": {"status": "pending"}},
        "actions": {"ship": {"operation": "set",
                             "path": "order.status", "value": "shipped"}}
    },
)
environment = wf.environments.from_template(
    project_id=project["id"],
    name="Warehouse A",
    template_id=template["id"],
)
for item in wf.environments.iter_all(project["id"]):
    print(item["id"], item["version"])
~~~

**What this is for:** a reusable **template** defines the base design. An **environment** is an independently editable copy. A **project** groups related resources. Definitions and revisions are stored through WorldFoundry's API in its private Supabase backend.

Update safely by reading the current version first:

~~~python
current = wf.environments.get(environment["id"])
edited = wf.environments.configure(
    environment["id"],
    expected_version=current["version"],
    config={**current["config"], "instruction": "Verify, then ship"},
)
history = wf.environments.versions(environment["id"])
~~~

`expected_version` prevents overwriting a concurrent edit. Other cloud resource managers include `scenarios`, `agents`, `datasets`, `policies`, `validators`, `tools`, `workflows` and `applications`. The API can paginate resource collections; it does **not** promise unlimited storage without capacity or quota limits. See [resource-library.md](resource-library.md).

## 9. Hosted simulation — state runs in WorldFoundry's service

Hosted `wf.simulations` is different from local `wf.training`. An existing developer agent can execute wherever the developer runs it and make HTTPS calls to a hosted **declarative** environment. The hosted service stores state and grades outcomes; it does **not** host arbitrary Python agent code.

~~~python
session = wf.simulations.start(
    project_id=project_id,
    environment_id=environment_id,
    scenario_id=scenario_id,
)
step = wf.simulations.act(
    session["id"], "ship",
    expected_version=session["version"],
    parameters={},
)
result = wf.simulations.submit(
    session["id"], expected_version=step["version"]
)
print(result["score"], result["checks"])
print(wf.simulations.events(session["id"]))
~~~

This snippet assumes that a **compatible environment and scenario have already been created**, and that the caller has authenticated hosted API access. `expected_version` protects state against conflicting calls. See [hosted-runtime.md](hosted-runtime.md). Do not confuse it with `worldfoundry serve`, which starts a local API.

## 10. Existing agent frameworks and experimental reality reconstruction

**MCP:** Install `pip install "worldfoundry[mcp]==0.8.0"`, start an episode locally, then expose that episode to a trusted MCP-capable local agent:

~~~bash
python -m worldfoundry.integrations.mcp --home .wf-data --episode ep_replace_me
~~~

**Google ADK:** `worldfoundry.integrations.adk.tools(wf, episode_id)` returns function wrappers suitable for a developer to integrate with ADK.

**Meta ARE:** `MetaARERunner` can launch an independently installed ARE scenario. It does **not** merge WorldFoundry episode state with ARE universes or turn ARE into the WorldFoundry engine.

**Reality reconstruction:** The experimental `reality` environment executes explicitly approved rules with guards and atomic effects. `ReferenceCase` and `verify_reference_cases` compare simulated results against **recorded reference outcomes**. `propose_actions` can suggest narrow candidate rules from observations; those are not certified behaviors and must be reviewed. Offline utilities `otlp_span_events`, `debezium_row_changes`, `directly_follows` and optional `pm4py_discover` analyze supplied event/trace data. These features do **not** automatically reproduce an enterprise system.

Use the tested examples and safety boundaries in [reality-engine.md](reality-engine.md).

## 11. Where each source file fits

### Developer-facing SDK — `src/worldfoundry/`

| File | What it does |
| --- | --- |
| [`client.py`](../src/worldfoundry/client.py) | Chooses local or cloud client; constructs local resource managers |
| [`cli.py`](../src/worldfoundry/cli.py) | Parses `worldfoundry` / `wf` terminal commands |
| [`engine.py`](../src/worldfoundry/engine.py) | Starts episodes, executes actions, handles traces and grading |
| [`environments.py`](../src/worldfoundry/environments.py) | Built-in support desk actions, state and validation |
| [`declarative.py`](../src/worldfoundry/declarative.py) | JSON environment interpreter, state operations, scenarios, checks |
| [`platform.py`](../src/worldfoundry/platform.py) | Local projects, environment/agent/scenario registries and batch training runs |
| [`extensibility.py`](../src/worldfoundry/extensibility.py) | Custom environment and snapshot connector registration |
| [`models.py`](../src/worldfoundry/models.py) | `Episode`, `ActionSpec`, `StepResult`, `ValidationResult` data shapes |
| [`store.py`](../src/worldfoundry/store.py) | Local episode files and JSONL export |
| [`server.py`](../src/worldfoundry/server.py) | Local HTTP API |
| [`snapshots.py`](../src/worldfoundry/snapshots.py) | Isolated snapshots of authorized external data |
| [`reality.py`](../src/worldfoundry/reality.py) | Experimental guarded state rules and reference verification |
| [`observation.py`](../src/worldfoundry/observation.py) | Offline OTLP/Debezium imports and process discovery |
| [`cloud.py`](../src/worldfoundry/cloud.py) | Hosted API transport and versioned cloud resource/simulation clients |
| [`managed.py`](../src/worldfoundry/managed.py) | Client methods for managed runs, artifacts, billing and connectors |
| [`integrations/`](../src/worldfoundry/integrations/) | ADK wrappers, MCP tool server and Meta ARE runner |

### Platform/backend code — not imported by customer applications

| Directory | Responsibility |
| --- | --- |
| [`supabase/functions/worldfoundry-customer-api/`](../supabase/functions/worldfoundry-customer-api/) | Authenticated customer APIs, resource CRUD, simulation and managed-run routes |
| [`supabase/migrations/`](../supabase/migrations/) | SQL schemas for protected resources, sessions and managed runs |
| [`backend/core/`](../backend/core/) | Server-side settings and Supabase access |
| [`backend/api/`](../backend/api/) | Private worker API and billing webhook application |
| [`backend/orchestration/`](../backend/orchestration/) | Managed job dispatch and Cloud Tasks integration |
| [`backend/workers/`](../backend/workers/) | Execution worker implementations |
| [`backend/billing/`](../backend/billing/) | Stripe integration scaffolding, webhooks and usage |
| [`runtime/`](../runtime/) | Server-side scripted simulation, replay and validation |
| [`gateway/`](../gateway/) | Public-facing API gateway/proxy |
| [`infrastructure/`](../infrastructure/) | Deployment files; current repo includes **Google Cloud Run/Cloud Tasks/Terraform**, not an implemented AWS deployment |

## 12. Current capabilities vs future work

| Capability | Current state |
| --- | --- |
| Local episodes, state changes, scoring, traces | Implemented |
| User-defined JSON environments and trusted Python plugins | Implemented locally |
| Existing local callable agent and sequential episode runs | Implemented |
| Offline evidence analysis and reference-case verification | Experimental local implementation |
| MCP/ADK adapters and standalone Meta ARE runner | Integration paths implemented; limitations above |
| Hosted Supabase-backed resource and JSON simulation code | Implemented/deployed components; onboarding/tenant verification incomplete |
| Arbitrary customer Python executed on WorldFoundry workers | **Not available** |
| Live enterprise system replicas and automatic rule discovery | **Not available** |
| Actual RL, fine-tuning or agent weight updates | **Not available** |
| Production-ready Stripe billing and managed compute | **Not available** |
| AWS-hosted production worker architecture | **Not implemented in this repository** |

## 13. Common mistakes

- **`worldfoundry` command not found:** Install the package in the active Python environment; check `python -m pip show worldfoundry`.
- **Wrong environment ID:** Run `worldfoundry environments list`; JSON imports yield resource IDs you can use when starting episodes.
- **Actions after submit fail:** Submission is terminal; start a new episode.
- **A plugin disappears after restarting:** Register/import the trusted Python module in every new process.
- **Cloud code does not authenticate:** A local installation is not a cloud account; a provisioned WorldFoundry API key and verified live onboarding are required.
- **No model learns despite successful episodes:** Evaluations and traces are outputs, not model-weight updates.
- **Confused by multiple versions in old documents:** Refer to `pyproject.toml` / `worldfoundry --version` for the installed SDK version and use this v0.8.0 guide as an index.

### Existing documentation and runnable source

- [Custom environment guide](custom-environments.md)
- [Resource library guide](resource-library.md)
- [Hosted runtime guide](hosted-runtime.md)
- [Experimental reality SDK](reality-engine.md)
- [SDK contract and boundaries](sdk-contract.md)
- [Python examples](../examples/)
- [Repository README](../README.md)

**Documentation principle:** Each developer-facing page should lead with a usable example, explain every parameter and output, then link to underlying source. Backend deployment instructions belong in a separate operator section, not the beginner quickstart.
