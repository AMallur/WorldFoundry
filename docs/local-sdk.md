# Local SDK reference

Start with the [quickstart](../README.md#quickstart). To install from a checkout, run `python -m pip install -e .` in the repository root.

## CLI

Keep state in a project-local folder while experimenting.

```bash
export WORLDFOUNDRY_HOME="$PWD/.wf-data"

worldfoundry environments list
worldfoundry episodes start support-desk --task incident-triage --seed 7
```

Copy the returned episode ID and use it to run actions in that simulation.

```bash
EPISODE_ID=ep_replace_me

worldfoundry episodes act "$EPISODE_ID" get_ticket \
  --params '{"ticket_id":"TCK-100"}'
worldfoundry episodes act "$EPISODE_ID" set_priority \
  --params '{"ticket_id":"TCK-100","priority":"critical"}'
worldfoundry episodes act "$EPISODE_ID" assign \
  --params '{"ticket_id":"TCK-100","assignee":"on-call"}'
worldfoundry episodes act "$EPISODE_ID" reply \
  --params '{"ticket_id":"TCK-100","message":"We acknowledge the outage and have opened an incident."}'
worldfoundry episodes act "$EPISODE_ID" resolve \
  --params '{"ticket_id":"TCK-100"}'
worldfoundry episodes submit "$EPISODE_ID"
worldfoundry traces export "$EPISODE_ID" --output trace.jsonl
```

Submission is a terminal gate. A submitted episode becomes `passed` or `failed` and rejects later
actions. Start a fresh episode for another attempt.

## Python SDK

```python
from worldfoundry import WorldFoundry

wf = WorldFoundry(".wf-data")
episode = wf.start("support-desk", task="incident-triage", seed=7)

wf.act(episode.id, "set_priority", ticket_id="TCK-100", priority="critical")
wf.act(episode.id, "assign", ticket_id="TCK-100", assignee="on-call")
wf.act(
    episode.id,
    "reply",
    ticket_id="TCK-100",
    message="We acknowledge the outage and have opened an incident.",
)
wf.act(episode.id, "resolve", ticket_id="TCK-100")

result = wf.submit(episode.id)
print(result.passed, result.score)
wf.export_trace(episode.id, "trace.jsonl")
```

For a complete runnable version, see [the Python example](../examples/python_episode.py).

## REST API and `curl`

Start the local server.

```bash
WORLDFOUNDRY_HOME="$PWD/.wf-data" worldfoundry serve --port 8787
```

Run these commands in a second terminal.

```bash
curl -s http://127.0.0.1:8787/health

curl -s -X POST http://127.0.0.1:8787/v1/episodes \
  -H 'content-type: application/json' \
  -d '{"environment":"support-desk","task":"incident-triage","seed":7}'

EPISODE_ID=ep_replace_me

curl -s -X POST "http://127.0.0.1:8787/v1/episodes/$EPISODE_ID/actions" \
  -H 'content-type: application/json' \
  -d '{"action":"set_priority","parameters":{"ticket_id":"TCK-100","priority":"critical"}}'

curl -s -X POST "http://127.0.0.1:8787/v1/episodes/$EPISODE_ID/submit"
curl -s "http://127.0.0.1:8787/v1/episodes/$EPISODE_ID/trace" > trace.jsonl
```

See [the shell example](../examples/curl_episode.sh) for a full REST run that extracts
the episode ID without requiring `jq`.

## Environment contract

Each environment supplies the following components.

1. An initial state generated from a seed.
2. A task instruction.
3. Named actions with parameter schemas.
4. Stateful action handlers that return observations.
5. Deterministic validators that produce individual checks, a score, and pass/fail.

All interfaces use the same engine and local store. State lives in
`$WORLDFOUNDRY_HOME/episodes` or `~/.worldfoundry/episodes` by default. Set the environment variable
or pass `WorldFoundry(path)` / `--home PATH` for isolated runs.

## Extensions

- [Create a JSON environment or a Python plugin](custom-environments.md)
- [Run a Python agent across multiple test cases](sdk-contract.md#working-locally)
- [Expose actions as Google ADK tools](adk.md)
- [Compare simulated outcomes with recorded examples](reality-engine.md)

Install `worldfoundry[mcp]` for the MCP tool bridge or `worldfoundry[process]` for optional PM4Py process discovery.
