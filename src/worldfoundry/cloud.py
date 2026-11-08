"""Explicit HTTP SDK transport for a separately deployed WorldFoundry API."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .platform import WorldFoundryError


class HTTPTransport:
    def __init__(self, base_url: str, api_key: str):
        if not base_url.startswith("https://") and not base_url.startswith("http://127.0.0.1:"):
            raise ValueError("Cloud API must use HTTPS (or loopback for development)")
        if not api_key:
            raise ValueError("api_key is required")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = json.dumps(body).encode() if body is not None else None
        req = Request(self.base_url + path, payload, {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }, method=method)
        try:
            with urlopen(req, timeout=30) as response:
                return json.load(response)
        except HTTPError as exc:
            raise WorldFoundryError(f"API returned HTTP {exc.code}") from exc
        except URLError as exc:
            raise WorldFoundryError(f"API unavailable: {exc.reason}") from exc


class CloudResourceManager:
    def __init__(self, transport: HTTPTransport, path: str):
        self.transport, self.path = transport, path

    def create(self, **parameters: Any) -> dict[str, Any]:
        return self.transport.request("POST", f"/v1/{self.path}", parameters)

    def register(self, **parameters: Any) -> dict[str, Any]:
        return self.create(**parameters)

    def get(self, resource_id: str) -> dict[str, Any]:
        return self.transport.request("GET", f"/v1/{self.path}/{resource_id}")

    def list(self) -> dict[str, Any]:
        return self.transport.request("GET", f"/v1/{self.path}")

    def update(self, resource_id: str, **parameters: Any) -> dict[str, Any]:
        return self.transport.request("PATCH", f"/v1/{self.path}/{resource_id}", parameters)

    def run(self, **parameters: Any) -> dict[str, Any]:
        return self.create(**parameters)


class CloudWorldFoundry:
    """Client contract; requires an independently deployed, authenticated API."""
    def __init__(self, *, base_url: str, api_key: str):
        transport = HTTPTransport(base_url, api_key)
        self.projects = CloudResourceManager(transport, "projects")
        self.environments = CloudResourceManager(transport, "environments")
        self.agents = CloudResourceManager(transport, "agents")
        self.scenarios = CloudResourceManager(transport, "scenarios")
        self.datasets = CloudResourceManager(transport, "datasets")
        self.policies = CloudResourceManager(transport, "policies")
        self.validators = CloudResourceManager(transport, "validators")
        self.runs = CloudResourceManager(transport, "training-runs")
        self.training = CloudTrainingManager(transport)
        self.episodes = CloudResourceManager(transport, "episodes")

    @classmethod
    def sign_in(cls, *, project_url: str, publishable_key: str,
                email: str, password: str) -> CloudWorldFoundry:
        """Exchange Supabase email/password for a user session; keep it in memory only."""
        if not project_url.startswith("https://"):
            raise ValueError("project_url must use HTTPS")
        endpoint = project_url.rstrip("/") + "/auth/v1/token?grant_type=password"
        req = Request(endpoint, json.dumps({"email": email, "password": password}).encode(), {
            "apikey": publishable_key, "Content-Type": "application/json",
        }, method="POST")
        try:
            with urlopen(req, timeout=30) as response:
                token = json.load(response)["access_token"]
        except (HTTPError, URLError) as exc:
            raise WorldFoundryError("Supabase sign-in failed") from exc
        return cls(base_url=project_url.rstrip("/") + "/functions/v1/worldfoundry-api",
                   api_key=token)


class CloudTrainingManager(CloudResourceManager):
    def __init__(self, transport: HTTPTransport):
        super().__init__(transport, "training-runs")

    def run_local(self, *, project_id: str, agent: dict[str, Any],
                  environment: dict[str, Any], handler: Any, episodes: int = 1,
                  seed: int = 0, data_dir: str | Path | None = None) -> dict[str, Any]:
        """Run user code on this computer, then sync scores to Supabase.

        The cloud record is not a managed execution claim. A process exit before sync
        leaves a running record that can be inspected and recovered by the caller.
        """
        from .client import WorldFoundry

        if not 1 <= episodes <= 10000:
            raise ValueError("episodes must be between 1 and 10000")
        run = self.create(project_id=project_id, agent_id=agent["id"],
                          environment_id=environment["id"], episodes=episodes,
                          execution="client", seed=seed)
        self.update(run["id"], status="running")
        with tempfile.TemporaryDirectory(prefix="worldfoundry-") if data_dir is None else _existing_dir(data_dir) as root:
            local = WorldFoundry.local(root)
            template = environment.get("config", {}).get("template", "support-desk")
            env = local.environments.create(template=template)
            registered = local.agents.register(name=agent["name"], handler=handler)
            result = local.training.create(agent=registered, environment=env, episodes=episodes, seed=seed)
            for ordinal, episode_id in enumerate(result.episode_ids):
                episode = local.get(episode_id)
                remote_episode = self.transport.request("POST", "/v1/episodes", {
                    "run_id": run["id"], "ordinal": ordinal, "seed": seed + ordinal,
                    "status": episode.status, "score": result.scores[ordinal],
                })
                self.transport.request("POST", f"/v1/episodes/{remote_episode['id']}/trace",
                                       {"events": episode.trace})
        completed = self.update(run["id"], status="completed")
        return {"run": completed, "summary": result.summary, "report_url": None}


class _existing_dir:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def __enter__(self) -> Path:
        self.path.mkdir(parents=True, exist_ok=True)
        return self.path

    def __exit__(self, *args: object) -> None:
        pass

