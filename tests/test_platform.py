import json

import pytest

from worldfoundry import WorldFoundry
from worldfoundry.platform import WorldFoundryError


def support_agent(instruction, tools):
    assert "outage" in instruction
    tools.set_priority(ticket_id="TCK-100", priority="critical")
    tools.assign(ticket_id="TCK-100", assignee="on-call")
    tools.reply(ticket_id="TCK-100", message="We acknowledge the outage and opened an incident.")
    tools.resolve(ticket_id="TCK-100")
    tools.submit()


def test_local_sdk_batch_and_report(tmp_path):
    wf = WorldFoundry.local(tmp_path)
    env = wf.environments.create(template="customer_support")
    agent = wf.agents.register(name="support", handler=support_agent)
    run = wf.training.create(agent=agent, environment=env, episodes=3, seed=10)
    assert run.wait().success_rate == 1
    assert len(run.episode_ids) == 3
    assert run.report_url is None
    assert json.loads(run.report_path.read_text())["scores"] == [1.0, 1.0, 1.0]
    assert len(wf.environments.list()) == 1
    assert all(wf.get(eid).status == "passed" for eid in run.episode_ids)


def test_budgets_and_unimplemented_execution_are_explicit(tmp_path):
    wf = WorldFoundry.local(tmp_path)
    with pytest.raises(WorldFoundryError, match="Only beginner"):
        wf.environments.create(template="customer_support", difficulty="advanced")
    env = wf.environments.create(template="customer_support")
    agent = wf.agents.register(name="support", handler=support_agent)
    with pytest.raises(WorldFoundryError, match="supported limits"):
        wf.training.create(agent=agent, environment=env, concurrency=4)
    with pytest.raises(WorldFoundryError, match="Remote agent endpoints"):
        wf.agents.register(name="remote", endpoint="https://example.com/agent")

