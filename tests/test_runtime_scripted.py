import copy

import pytest

from backend.connectors.base import JSONSnapshotConnector
from runtime.scripted import ScenarioError, run_plan


ENV = {
    "initial_state": {"tickets": {"T1": {"status": "open", "notes": []}}},
    "actions": {
        "close": {"operation": "set", "path": "tickets.$id.status", "value": "closed",
                  "parameters": {"id": {"type": "string"}}},
        "note": {"operation": "append", "path": "tickets.$id.notes", "from_param": "note",
                 "parameters": {"id": {"type": "string"}, "note": {"type": "string"}}},
    },
}
SCENARIO = {"checks": [
    {"name": "closed", "path": "tickets.T1.status", "equals": "closed"},
    {"name": "noted", "path": "tickets.T1.notes", "equals": ["reviewed"]},
]}
PLAN = [
    {"action": "close", "parameters": {"id": "T1"}},
    {"action": "note", "parameters": {"id": "T1", "note": "reviewed"}},
]


def test_stateful_training_and_repeatable_feedback():
    starting = copy.deepcopy(ENV)
    first = run_plan(ENV, SCENARIO, PLAN, seed=22)
    second = run_plan(ENV, SCENARIO, PLAN, seed=22)
    assert first.passed and first.score == 1
    assert second.events == first.events
    assert ENV == starting
    assert first.actions == 2


def test_reject_untrusted_actions():
    with pytest.raises(ScenarioError):
        run_plan(ENV, SCENARIO, [{"action": "close", "parameters": {"id": "__proto__"}}])
    with pytest.raises(ScenarioError):
        run_plan(ENV, SCENARIO, [{"action": "unknown", "parameters": {}}])


def test_snapshot_is_read_only():
    data = {"tickets": {"T1": {"status": "open"}}}
    connector = JSONSnapshotConnector(data)
    snapshot = connector.snapshot()
    snapshot["tickets"]["T1"]["status"] = "closed"
    assert data["tickets"]["T1"]["status"] == "open"
