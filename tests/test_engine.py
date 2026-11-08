import json

import pytest

from worldfoundry import WorldFoundry
from worldfoundry.environments import EnvironmentError


def complete_episode(client: WorldFoundry) -> str:
    episode = client.start("support-desk", seed=42)
    client.act(episode.id, "set_priority", ticket_id="TCK-100", priority="critical")
    client.act(episode.id, "assign", ticket_id="TCK-100", assignee="on-call")
    client.act(
        episode.id,
        "reply",
        ticket_id="TCK-100",
        message="We acknowledge this outage and opened incident INC-42.",
    )
    client.act(episode.id, "resolve", ticket_id="TCK-100")
    return episode.id


def test_passing_episode_and_trace_export(tmp_path):
    client = WorldFoundry(tmp_path / "state")
    episode_id = complete_episode(client)
    result = client.submit(episode_id)

    assert result.passed is True
    assert result.score == 1.0
    assert client.get(episode_id).status == "passed"

    target = client.export_trace(episode_id, tmp_path / "trace.jsonl")
    events = [json.loads(line) for line in target.read_text().splitlines()]
    assert [event["sequence"] for event in events] == list(range(len(events)))
    assert events[0]["type"] == "episode.started"
    assert events[-1]["type"] == "episode.submitted"


def test_failed_action_is_traced_without_mutating_state(tmp_path):
    client = WorldFoundry(tmp_path)
    episode = client.start("support-desk")

    with pytest.raises(EnvironmentError, match="Unknown assignee"):
        client.act(episode.id, "assign", ticket_id="TCK-100", assignee="nobody")

    saved = client.get(episode.id)
    assert saved.state["tickets"]["TCK-100"]["assignee"] is None
    assert saved.trace[-1]["type"] == "action.failed"


def test_invalid_parameter_and_terminal_submission(tmp_path):
    client = WorldFoundry(tmp_path)
    episode_id = complete_episode(client)

    with pytest.raises(EnvironmentError, match="must be one of"):
        other = client.start("support-desk")
        client.act(other.id, "set_priority", ticket_id="TCK-100", priority="urgent")

    client.submit(episode_id)
    with pytest.raises(EnvironmentError, match="no more actions"):
        client.act(episode_id, "get_ticket", ticket_id="TCK-100")


def test_incomplete_episode_fails_with_partial_score(tmp_path):
    client = WorldFoundry(tmp_path)
    episode = client.start("support-desk")
    client.act(episode.id, "set_priority", ticket_id="TCK-100", priority="critical")
    result = client.submit(episode.id)
    assert result.passed is False
    assert result.score == 0.2

