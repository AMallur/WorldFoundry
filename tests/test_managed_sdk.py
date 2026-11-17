from pathlib import Path

import pytest

from worldfoundry.managed import CloudArtifacts, CloudBilling, CloudManagedRuns


class StubTransport:
    def __init__(self):
        self.calls = []

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        return {"id": "run-a", "status": "completed", "score_mean": 1.0}


def test_managed_run_contract_and_wait():
    transport = StubTransport()
    manager = CloudManagedRuns(transport)
    run = manager.create(project_id="p", agent_id="a", environment_id="e",
                         scenario_id="s", episodes=2, idempotency_key="job-unique-1")
    assert run["status"] == "completed"
    assert transport.calls[0][1] == "/v1/managed-runs"
    assert transport.calls[0][2]["idempotency_key"] == "job-unique-1"
    assert manager.wait("run-a")["status"] == "completed"


def test_artifact_and_billing_paths(tmp_path: Path):
    path = tmp_path / "example.json"
    path.write_text('{"a":1}')
    transport = StubTransport()
    CloudArtifacts(transport).upload_dataset(project_id="p", path=path)
    assert transport.calls[0][2]["content_base64"] == "eyJhIjoxfQ=="
    CloudBilling(transport).entitlement("p")
    assert transport.calls[1][1].startswith("/v1/billing/entitlement")


def test_upload_limit(tmp_path: Path):
    path = tmp_path / "large.bin"
    path.write_bytes(b"x" * 524289)
    with pytest.raises(ValueError, match="512"):
        CloudArtifacts(StubTransport()).upload_dataset(project_id="p", path=path)
