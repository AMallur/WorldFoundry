"""WorldFoundry hosted managed-run, artifact, connector and billing API clients."""
from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4


class CloudManagedRuns:
    """Run declarative agent plans on WorldFoundry-managed execution services."""

    def __init__(self, transport: Any):
        self.transport = transport

    def create(self, *, project_id: str, environment_id: str, scenario_id: str,
               agent_id: str, episodes: int = 1, max_steps: int = 30, seed: int = 0,
               executor: str = "edge_scripted", idempotency_key: str | None = None
               ) -> dict[str, Any]:
        if not 1 <= episodes <= 100 or not 1 <= max_steps <= 100:
            raise ValueError("episodes or max_steps outside 1..100")
        return self.transport.request("POST", "/v1/managed-runs", {
            "project_id": project_id, "environment_id": environment_id,
            "scenario_id": scenario_id, "agent_id": agent_id,
            "episodes": episodes, "max_steps": max_steps, "seed": seed,
            "executor": executor, "idempotency_key": idempotency_key or uuid4().hex,
        })

    def get(self, run_id: str) -> dict[str, Any]:
        return self.transport.request("GET", f"/v1/managed-runs/{run_id}")

    def list(self, project_id: str) -> dict[str, Any]:
        return self.transport.request("GET", "/v1/managed-runs?project_id="
                                      + quote(project_id, safe=""))

    def episodes(self, run_id: str) -> dict[str, Any]:
        return self.transport.request("GET", f"/v1/managed-runs/{run_id}/episodes")

    def artifacts(self, run_id: str) -> dict[str, Any]:
        return self.transport.request("GET", f"/v1/managed-runs/{run_id}/artifacts")

    def wait(self, run_id: str, *, timeout: float = 300, interval: float = 2
             ) -> dict[str, Any]:
        """Poll the server for run completion; never implies background work by the SDK."""
        if timeout < 0 or interval <= 0:
            raise ValueError("timeout must be nonnegative and interval must be positive")
        deadline = time.monotonic() + timeout
        while True:
            run = self.get(run_id)
            if run["status"] in ("completed", "failed", "cancelled"):
                return run
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Run {run_id} did not finish within {timeout} seconds")
            time.sleep(min(interval, max(0, deadline - time.monotonic())))


class CloudArtifacts:
    def __init__(self, transport: Any):
        self.transport = transport

    def upload_dataset(self, *, project_id: str, path: str | Path) -> dict[str, Any]:
        source = Path(path)
        if source.stat().st_size > 524288:
            raise ValueError("Inline dataset upload limit is 512 KiB")
        return self.transport.request("POST", "/v1/artifacts", {
            "project_id": project_id, "name": source.name, "kind": "dataset",
            "content_base64": base64.b64encode(source.read_bytes()).decode("ascii"),
        })

    def list(self, project_id: str) -> dict[str, Any]:
        return self.transport.request("GET", "/v1/artifacts?project_id="
                                      + quote(project_id, safe=""))

    def download_url(self, artifact_id: str) -> dict[str, Any]:
        return self.transport.request("GET", f"/v1/artifacts/{artifact_id}/download")


class CloudBilling:
    def __init__(self, transport: Any):
        self.transport = transport

    def entitlement(self, project_id: str) -> dict[str, Any]:
        return self.transport.request("GET", "/v1/billing/entitlement?project_id="
                                      + quote(project_id, safe=""))

    def usage(self, project_id: str) -> dict[str, Any]:
        return self.transport.request("GET", "/v1/billing/usage?project_id="
                                      + quote(project_id, safe=""))

    def create_checkout(self, project_id: str) -> dict[str, Any]:
        """Requires an enabled, separately configured Stripe billing service."""
        return self.transport.request("POST", "/v1/billing/checkout", {
            "project_id": project_id,
        })


class CloudConnectors:
    def __init__(self, transport: Any):
        self.transport = transport

    def catalog(self) -> dict[str, Any]:
        return self.transport.request("GET", "/v1/connectors")
