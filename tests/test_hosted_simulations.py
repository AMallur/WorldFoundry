"""Hosted simulation client transport contract tests."""
from worldfoundry.cloud import CloudSimulationManager


class FakeTransport:
    def __init__(self):
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        return {"id": "session-one", "version": 1}


def test_hosted_simulation_sdk_contract():
    transport = FakeTransport()
    manager = CloudSimulationManager(transport)
    manager.start(project_id="p", environment_id="e", scenario_id="s", max_steps=12)
    manager.act("session-one", "resolve", expected_version=0,
                parameters={"ticket_id": "T-1"}, call_id="test-call-123")
    manager.submit("session-one", expected_version=1, call_id="test-submit-123")
    manager.events("session-one")
    manager.list("p")
    assert transport.calls[0] == ("POST", "/v1/simulation-sessions", {
        "project_id": "p", "environment_id": "e", "scenario_id": "s",
        "seed": 0, "max_steps": 12,
    })
    assert transport.calls[1] == ("POST", "/v1/simulation-sessions/session-one/actions", {
        "action": "resolve", "parameters": {"ticket_id": "T-1"},
        "expected_version": 0, "call_id": "test-call-123",
    })
    assert transport.calls[2][1].endswith("/submit")
    assert transport.calls[3] == ("GET", "/v1/simulation-sessions/session-one/events", None)
    assert transport.calls[4] == ("GET", "/v1/simulation-sessions?project_id=p", None)
