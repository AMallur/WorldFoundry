# Google ADK integration

The local package exposes framework-neutral Python functions instead of taking a hard dependency
on Google ADK:

```python
from worldfoundry import WorldFoundry
from worldfoundry.integrations.adk import tools

client = WorldFoundry(".wf-data")
episode = client.start("support-desk")
agent_tools = tools(client, episode.id)
```

In an ADK application, pass `agent_tools` to the agent's `tools` argument. The agent can call
`worldfoundry_action(action, parameters)` repeatedly and then call `worldfoundry_submit()`.

The application, not the adapter, controls the model, retry policy, budgets, and loop termination.
Treat a validation result as an evaluation signal; this adapter does not train or update model
weights.

Before publishing a dedicated `worldfoundry-adk` extra, pin a supported ADK version, add an
end-to-end example against that version, and test generated function schemas in CI.

