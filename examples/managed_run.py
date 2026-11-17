"""Execute a WorldFoundry managed simulation using configured resource IDs."""
import os

from worldfoundry import WorldFoundry

wf = WorldFoundry(api_key=os.environ["WORLDFOUNDRY_API_KEY"])
project = os.environ["WF_PROJECT_ID"]
run = wf.managed_runs.create(
    project_id=project,
    environment_id=os.environ["WF_ENVIRONMENT_ID"],
    scenario_id=os.environ["WF_SCENARIO_ID"],
    agent_id=os.environ["WF_AGENT_ID"],
    episodes=2,
)
print(run["id"], run["status"], run.get("score_mean"))
print(wf.managed_runs.episodes(run["id"]))
print(wf.managed_runs.artifacts(run["id"]))
print(wf.billing.usage(project))
