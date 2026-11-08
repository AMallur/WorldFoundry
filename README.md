# WorldFoundry

**Training infrastructure for AI agents.**

WorldFoundry gives developers programmable environments where agents can practice real-world
tasks, interact with simulated systems, learn from failures, and improve through repeated
experiences.

Build agents anywhere. Train and test them in WorldFoundry.

> **Current status:** this repository builds the `worldfoundry` distribution locally. It has not
> been uploaded to PyPI or Homebrew. The commands labeled **verified local** below run from this checkout;
> commands under **future distribution** are intended product UX, not currently live installs.

## What works now

- A Python SDK and `worldfoundry` / `wf` command-line interface.
- Persistent, stateful episodes in a simulated support desk.
- Declared action schemas and validation before actions mutate state.
- Deterministic task grading with per-check results and a numeric score.
- Complete traces for starts, successful actions, failed actions, and submissions.
- JSONL trace export.
- A dependency-free REST API usable with `curl`.
- Framework-neutral callables ready to wrap as Google ADK function tools.
- Local SDK resource registration and sequential callable-agent batch runs with JSON reports.

This is trajectory and evaluation infrastructure. It does **not** perform reinforcement learning,
fine-tuning, reward-model training, or model-weight updates.

The expanded SDK contract and its current limits are in [`docs/sdk-contract.md`](docs/sdk-contract.md).
The Supabase control-plane schema, private trace storage, and authenticated Edge API are deployed;
managed Python workers and customer billing are not yet deployed.

The cloud usage ledger records client-reported episodes for operational visibility; it is not a
billing system. Stripe subscriptions, verified managed-compute usage, and payment webhooks are not
connected. The source includes a GitHub trusted-publishing workflow, but it cannot publish until
this directory is connected to a repository and a PyPI owner configures that repository as a
trusted publisher.

## Install — verified local

From this repository:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
worldfoundry --version
```

With `uv`, without keeping a virtual environment:

```bash
uvx --python 3.13 --from . worldfoundry --version
```

The explicit Python version makes the verification environment reproducible; any supported
Python 3.11–3.13 interpreter can be used.

### Future distribution — not published today

These are the intended commands after names are reserved and release pipelines publish artifacts:

```bash
# FUTURE: these package/formula names are not asserted to exist yet
pip install worldfoundry
uvx worldfoundry
brew install worldfoundry/tap/worldfoundry
```

## One-minute CLI experience

Keep state in a project-local folder while experimenting:

```bash
export WORLDFOUNDRY_HOME="$PWD/.wf-data"

worldfoundry environments list
worldfoundry episodes start support-desk --task incident-triage --seed 7
```

Copy the returned episode ID, then act inside the same persistent simulation:

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

A complete runnable version is in [`examples/python_episode.py`](examples/python_episode.py).

## REST API and `curl`

Start the local server:

```bash
WORLDFOUNDRY_HOME="$PWD/.wf-data" worldfoundry serve --port 8787
```

In another terminal:

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

See [`examples/curl_episode.sh`](examples/curl_episode.sh) for an end-to-end REST run that extracts
the episode ID without requiring `jq`.

## Environment contract

Each environment supplies:

1. An initial state generated from a seed.
2. A task instruction.
3. Named actions with parameter schemas.
4. Stateful action handlers that return observations.
5. Deterministic validators that produce individual checks, a score, and pass/fail.

All interfaces use the same engine and local store. State lives in
`$WORLDFOUNDRY_HOME/episodes` or `~/.worldfoundry/episodes` by default. Set the environment variable
or pass `WorldFoundry(path)` / `--home PATH` for isolated runs.

## Google ADK integration path

`worldfoundry.integrations.adk.tools(client, episode_id)` returns two documented Python callables:
one for environment actions and one for submission. Google ADK can wrap them as function tools
without making ADK a hard dependency of the core package. See [`docs/adk.md`](docs/adk.md).

## Path to hosted SaaS

The local contract deliberately maps to a hosted service:

| Local MVP | Hosted evolution |
|---|---|
| File-backed episode store | Transactional database plus object storage |
| In-process environment | Isolated worker or sandbox per episode |
| Local identity | API keys, workspaces, roles, and scoped tokens |
| Synchronous action | Idempotent action endpoint with call IDs |
| JSONL file | Queryable traces plus immutable export |
| One built-in environment | Versioned environment registry and private environments |
| Deterministic validator | Versioned eval suites, cohorts, and regression dashboards |

Before a public service, add idempotency keys, optimistic concurrency, tenant isolation, quotas,
signed artifacts, structured logs, worker timeouts, and compatibility tests for environment
versions. See [`docs/roadmap.md`](docs/roadmap.md) for release gates.

## Develop and test

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest
python -m compileall -q src tests examples
```

The test suite covers a passing SDK episode, failed-action trace recording, CLI persistence and
export, REST behavior, invalid parameters, and terminal submission semantics.

## License

Apache-2.0. See [`LICENSE`](LICENSE).

