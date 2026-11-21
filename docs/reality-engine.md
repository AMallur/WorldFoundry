# Reality reconstruction SDK — local experimental implementation

This is an evidence-backed workflow simulator, **not** an identical copy of any
enterprise system. It uses explicit business rules and measured reference
outcomes rather than inventing unknown application behavior.

## Currently implemented

- A stateful reality environment with typed action parameters, permission /
  business-rule guards, and multiple atomic state changes per action.
- Approval gate: no generated rule executes until the configuration contains
  approved=true. Human review and independently observed tests are required.
- Candidate rule proposals from repeated before/after state samples, with
  unsupported patterns explicitly rejected. Only constant and parameter-driven
  scalar assignments are inferred.
- Offline differential verification against recorded reference outcomes.
- Reference-case to evaluation-scenario candidate conversion.
- OpenAPI endpoint inventory (does not infer behavior from schemas).
- A local stdio MCP bridge bound to one existing WorldFoundry episode.
- A bounded Meta ARE CLI runner for independently installed ARE scenarios.

## Running an actual local simulation

~~~python
from worldfoundry import WorldFoundry, ReferenceCase, verify_reference_cases

settings = {
    "approved": True,  # Explicitly reviewed, tested business rules.
    "initial_state": {"requests": {"R1": {"status": "pending", "access": False}}},
    "actions": {
        "grant": {
            "parameters": {"request_id": {"type": "string"}},
            "guards": [{"path": "requests.$request_id.status",
                        "operator": "eq", "value": "pending"}],
            "effects": [
                {"operation": "set", "path": "requests.$request_id.status",
                 "value": "approved"},
                {"operation": "set", "path": "requests.$request_id.access",
                 "value": True},
            ],
        },
    },
    "checks": [{"name": "access", "path": "requests.R1.access", "equals": True}],
}

wf = WorldFoundry.local(".wf-data")
resource = wf.environments.create(template="reality", config=settings)
episode = wf.start(resource.id)
wf.act(episode.id, "grant", request_id="R1")
print(wf.submit(episode.id).to_dict())

# Verify against a recorded, independently established reference outcome.
case = ReferenceCase(
    action="grant",
    before={"requests": {"R1": {"status": "pending", "access": False}}},
    after={"requests": {"R1": {"status": "approved", "access": True}}},
    parameters={"request_id": "R1"},
    case_id="sandbox-reference-1",
)
print(verify_reference_cases(settings, [case]))
~~~

Draft proposals are not executable as-is:

~~~python
from worldfoundry import propose_actions
proposal = propose_actions([case_a, case_b])
print(proposal["actions"], proposal["rejected"])
# Independently verify each rule, permissions and unobserved branches.
# Compose initial_state, checks, guards and approved=True manually.
~~~

## Connecting an existing agent

For any MCP-capable local agent:

~~~bash
pip install "worldfoundry[mcp]"
python -m worldfoundry.integrations.mcp --home .wf-data --episode ep_replace_me
~~~

Register this stdio process in the trusted agent's MCP configuration. Tools:
worldfoundry_actions, worldfoundry_action and worldfoundry_submit. This is
**local** and has no public authentication or hosted multi-tenant isolation.
Never expose the stdio server as an unauthenticated public endpoint.

For standalone Meta ARE scenarios:

~~~python
from worldfoundry.integrations.meta_are import MetaARERunner
result = MetaARERunner(use_uvx=True).run(
    "scenario_find_image_file", provider="mock"
)
print(result.exit_code, result.stdout)
~~~

This wraps the ARE executable. It does not automatically convert WorldFoundry
definitions to ARE universes or share their world state.

## What is not yet implemented

| Capability | Status |
|---|---|
| Local atomic app rules and deterministic evaluation | Implemented |
| Evidence-based candidate-rule proposals | Implemented, narrow scope |
| Offline reference outcome comparison | Implemented |
| OpenAPI endpoint inventory | Implemented, no API server generation |
| MCP stdio bridge | Implemented, optional dependency |
| Independent Meta ARE runner | Implemented, no shared state |
| Authorized live-system test collection | Not implemented |
| OpenTelemetry / Debezium streaming collectors | Not implemented |
| Full PM4Py process discovery | Not implemented |
| Live ServiceNow / Salesforce / SAP connectors | Not implemented |
| Auto-discovery of hidden rules, failures, asynchronous side effects | Not implemented |
| Distributed multi-agent virtual-time execution | Not implemented |
| Hosted Supabase execution for Python reality environments | Not implemented |
| Live differential tests, drift monitoring, security accreditation | Not implemented |
| Actual RL / fine-tuning of agent model weights | Not implemented |

The separately deployed Supabase declarative runtime does not execute local
Python plugins. The user must not mistake an imported API, demo match, or
proposed rule for a validated commercial replica.

## Data and security rules

Only record cases from authorized test systems. Prefer read-only snapshots,
avoid active probing of production endpoints, and redact personal information
and trade secrets before importing evidence. Common credential key names are
rejected, but automatic redaction is not a comprehensive privacy control.
Do not place live OAuth secrets in resources or test fixtures.

Run the unit tests with:

~~~bash
python -m pip install -e ".[dev]"
pytest tests/test_reality_engine.py
ruff check src tests
~~~

See custom-environments.md, sdk-contract.md, and hosted-runtime.md for the
existing release boundaries.
