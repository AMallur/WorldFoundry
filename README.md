# WorldFoundry

**Test what your AI agent actually does.**

Run your agent against a simulated help desk before it touches real tickets. Did it mark the outage critical, assign it to the on-call engineer, send the required reply, and close the ticket? Rerun the same test after a prompt or model change and see which checks passed.

**[Try the incident challenge](https://worldfoundry-demo.vercel.app/?scenario=race)** · [Install and run locally](#quickstart) · [Connect a model](https://github.com/AMallur/WorldFoundry/blob/main/docs/with-your-model.md)

In the browser, click **Run a failing workflow** to see the missed checks. Then click **Take control and fix it**. This demo uses scripted actions and the WorldFoundry SDK. No signup, install, or key.

## Quickstart

Install with Python 3.11 or newer, ideally in your project's virtual environment.

```bash
python -m pip install worldfoundry
```

Save this as `first_test.py` and run `python first_test.py`. The example uses sample tickets entirely on your machine.

```python
from worldfoundry import WorldFoundry

wf = WorldFoundry(".wf-data")
episode = wf.start("support-desk")
wf.act(episode.id, "set_priority", ticket_id="TCK-100", priority="critical")
wf.act(episode.id, "assign", ticket_id="TCK-100", assignee="on-call")
wf.act(episode.id, "reply", ticket_id="TCK-100", message="We acknowledge the outage and incident.")
wf.act(episode.id, "resolve", ticket_id="TCK-100")
result = wf.submit(episode.id)
print(f"{sum(check.passed for check in result.checks)}/{len(result.checks)} checks passed")
```

You should see `5/5 checks passed`. Remove the `assign` line and run it again to see `4/5`.

## Use it with your stack

| I want to… | Start here |
| --- | --- |
| Run the same ticket test with GPT, Gemini, Claude, or a local Ollama model | [Connect a model](https://github.com/AMallur/WorldFoundry/blob/main/docs/with-your-model.md) |
| Use my own Python agent or Google ADK app | [Python agent example](https://github.com/AMallur/WorldFoundry/blob/main/examples/sdk_training.py) · [Google ADK tools](https://github.com/AMallur/WorldFoundry/blob/main/docs/adk.md) |
| Test my own workflow | [Build a test environment in JSON or Python](https://github.com/AMallur/WorldFoundry/blob/main/docs/custom-environments.md) |
| Use the CLI, export action traces, or call the local REST API | [Local SDK reference](https://github.com/AMallur/WorldFoundry/blob/main/docs/local-sdk.md) |

## More docs

[SDK contract](https://github.com/AMallur/WorldFoundry/blob/main/docs/sdk-contract.md) · [Recorded workflows](https://github.com/AMallur/WorldFoundry/blob/main/docs/reality-engine.md) · [Hosted simulation beta](https://github.com/AMallur/WorldFoundry/blob/main/docs/hosted-runtime.md) · [Resource library](https://github.com/AMallur/WorldFoundry/blob/main/docs/resource-library.md) · [Managed platform](https://github.com/AMallur/WorldFoundry/blob/main/docs/managed-platform.md) · [Roadmap](https://github.com/AMallur/WorldFoundry/blob/main/docs/roadmap.md)

Local simulations score actions and final state using explicit checks. Hosted simulation is in beta. See the [customer/cloud boundary](https://github.com/AMallur/WorldFoundry/blob/main/docs/customer-company-boundary.md) and [cloud key guide](https://github.com/AMallur/WorldFoundry/blob/main/docs/api-keys.md) for availability.
