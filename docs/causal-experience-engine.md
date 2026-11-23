# Causal Experience Engine: failure-boundary discovery (experimental)

## The one-minute value proposition

**Find the smallest changes to a task that break your existing agent.**
Instead of writing dozens of evaluation cases by hand, define the conditions
you want to vary. WorldFoundry runs the agent on paired scenarios and reports
which changes correlate with failure.

This first version **discovers failure boundaries**. It does not automatically
train model weights, establish causal mechanisms, guarantee improvements, or
have a proprietary moat merely because the code exists.

## Run it without cloud setup

```python
from worldfoundry.causal import Factor, discover

def my_agent_test(scenario, seed):
    # Replace with an actual agent invocation; return True if it succeeds.
    return not scenario["ticket"]["approval_required"]

report = discover(
    my_agent_test,
    [
        Factor("ticket.approval_required", False, (False, True)),
        Factor("ticket.priority", "normal", ("normal", "urgent")),
    ],
    budget=30,
    trials=3,
)
for finding in report.boundaries:
    print(finding.changes, finding.risk_difference)
```

No credentials, server, model provider, or additional dependencies required.

## Connect an existing WorldFoundry agent

```python
from worldfoundry import WorldFoundry
from worldfoundry.causal import Factor, discover, worldfoundry_evaluator

wf = WorldFoundry.local(".wf-data")
agent = wf.agents.register(name="my-agent", handler=my_agent)
env = wf.environments.create(template="declarative", config=my_environment_config)
evaluate = worldfoundry_evaluator(wf, agent, env)

report = discover(
    evaluate,
    [Factor("order.requires_approval", False, (False, True))],
    budget=20,
    trials=5,
)
print(report.to_dict())
```

Factor paths address fields under `scenario.state_overrides`; the fields must
exist or be valid for the environment. Each candidate uses a fresh episode.
Agent handlers run locally, and may invoke external models at their own cost.

## Guarantees and limits

- Candidate order prioritizes single-field changes, then two-field combinations.
- Paired baseline and variant trials receive the same seeds; external models
  may ignore seed controls.
- A user-supplied `valid` predicate can reject impossible combinations.
- Total episode evaluations never exceed `budget`.
- Baseline trials consume part of the budget.
- Wilson-based intervals are descriptive and not proof of causality.
- Each discovery may leave episode traces in the user's local store.
- This version does not automatically update agents or measure held-out gains.
- Factor combinations grow exponentially; narrow factor sets are recommended.
- The algorithm is a transparent initial baseline, not a validated unique invention.

## Next engineering milestone

Add adaptive candidate prioritization and minimization, independent reruns,
held-out evaluation, and a real adaptation interface. Benchmark against random
scenario search at equal cost before making superiority claims. Protect
customer data through opt-in collection and tenant isolation; no cross-customer
data sharing is implemented here.
