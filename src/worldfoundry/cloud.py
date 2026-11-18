"""Explicit HTTP SDK transport for a separately deployed WorldFoundry API."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import uuid4

from .managed import CloudArtifacts, CloudBilling, CloudConnectors, CloudManagedRuns
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
    """Typed remote resources; WorldFoundry API mediates all Supabase access."""

    def __init__(self, transport: HTTPTransport, path: str):
        self.transport, self.path = transport, path

    def create(self, **parameters: Any) -> dict[str, Any]:
        """Create a new version-1 resource under a customer-owned project.

        Supply either config={...} or explicit environment fields as kwargs.
        Never supply a Supabase service key to this method.
        """
        return self.transport.request("POST", f"/v1/{self.path}", parameters)

    def register(self, **parameters: Any) -> dict[str, Any]:
        return self.create(**parameters)

    def get(self, resource_id: str) -> dict[str, Any]:
        return self.transport.request("GET", f"/v1/{self.path}/{quote(resource_id, safe='')}")

    def list(self, project_id: str | None = None, *, limit: int = 50,
             offset: int = 0, include_archived: bool = False) -> dict[str, Any]:
        """Fetch up to 100 records; use next_offset for complete pagination."""
        if not 1 <= limit <= 100 or not 0 <= offset <= 9_007_199_254_740_991:
            raise ValueError("limit must be 1..100 and offset must be a nonnegative safe integer")
        args = [f"limit={limit}", f"offset={offset}"]
        if project_id is not None:
            args.append("project_id=" + quote(project_id, safe=""))
        if include_archived:
            args.append("include_archived=true")
        return self.transport.request("GET", f"/v1/{self.path}?" + "&".join(args))

    def iter_all(self, project_id: str, *, page_size: int = 100,
                 include_archived: bool = False):
        """Lazily iterate any number of resources without loading all at once."""
        offset = 0
        while True:
            page = self.list(project_id, limit=page_size, offset=offset,
                             include_archived=include_archived)
            yield from page.get("data", [])
            offset = page.get("next_offset")
            if offset is None:
                break

    def update(self, resource_id: str, **parameters: Any) -> dict[str, Any]:
        """Resource changes need expected_version, protecting concurrent edits.

        This generic manager also serves training-runs, whose status update
        interface remains unchanged.
        """
        return self.transport.request("PATCH",
                                      f"/v1/{self.path}/{quote(resource_id, safe='')}",
                                      parameters)

    def configure(self, resource_id: str, *, expected_version: int,
                  config: dict[str, Any], name: str | None = None) -> dict[str, Any]:
        if expected_version < 1 or not isinstance(config, dict):
            raise ValueError("expected_version and dict config are required")
        payload: dict[str, Any] = {"expected_version": expected_version, "config": config}
        if name is not None:
            payload["name"] = name
        return self.update(resource_id, **payload)

    def versions(self, resource_id: str, *, limit: int = 50,
                 offset: int = 0) -> dict[str, Any]:
        if not 1 <= limit <= 100 or not 0 <= offset <= 1_000_000:
            raise ValueError("Invalid pagination")
        return self.transport.request("GET",
            f"/v1/{self.path}/{quote(resource_id, safe='')}/versions"
            f"?limit={limit}&offset={offset}")

    def version(self, resource_id: str, version: int) -> dict[str, Any]:
        if version < 1:
            raise ValueError("version must be positive")
        return self.transport.request("GET",
            f"/v1/{self.path}/{quote(resource_id, safe='')}/versions/{version}")

    def restore(self, resource_id: str, *, version: int,
                expected_version: int) -> dict[str, Any]:
        """Restore a historical snapshot into a NEW version."""
        return self.transport.request("POST",
            f"/v1/{self.path}/{quote(resource_id, safe='')}/restore",
            {"version": version, "expected_version": expected_version})

    def archive(self, resource_id: str, *, expected_version: int) -> dict[str, Any]:
        """Soft-delete, retaining histories and references for existing runs."""
        return self.transport.request("POST",
            f"/v1/{self.path}/{quote(resource_id, safe='')}/archive",
            {"expected_version": expected_version})

    def unarchive(self, resource_id: str, *, expected_version: int) -> dict[str, Any]:
        return self.transport.request("POST",
            f"/v1/{self.path}/{quote(resource_id, safe='')}/unarchive",
            {"expected_version": expected_version})

    def from_template(self, *, project_id: str, name: str, template_id: str,
                      overrides: dict[str, Any] | None = None,
                      template_version: int | None = None) -> dict[str, Any]:
        if self.path != "environments":
            raise ValueError("Only environments can be instantiated from templates")
        data: dict[str, Any] = {
            "project_id": project_id, "name": name, "template_id": template_id,
            "overrides": overrides or {},
        }
        if template_version is not None:
            data["template_version"] = template_version
        return self.create(**data)

    def run(self, **parameters: Any) -> dict[str, Any]:
        return self.create(**parameters)



class CloudSimulationManager:
    """Remote stateful simulations powered by WorldFoundry's hosted API.

    Customer Python agents stay in their own process. Only declarative
    environment state and validated actions run on the hosted service.
    """

    def __init__(self, transport: HTTPTransport):
        self.transport = transport

    def start(self, *, project_id: str, environment_id: str, scenario_id: str,
              seed: int = 0, max_steps: int = 30) -> dict[str, Any]:
        return self.transport.request("POST", "/v1/simulation-sessions", {
            "project_id": project_id, "environment_id": environment_id,
            "scenario_id": scenario_id, "seed": seed, "max_steps": max_steps,
        })

    def get(self, session_id: str) -> dict[str, Any]:
        return self.transport.request("GET", f"/v1/simulation-sessions/{session_id}")

    def list(self, project_id: str) -> dict[str, Any]:
        return self.transport.request("GET", "/v1/simulation-sessions?project_id="
                                      + quote(project_id, safe=""))

    def act(self, session_id: str, action: str, *, expected_version: int,
            parameters: dict[str, Any] | None = None,
            call_id: str | None = None) -> dict[str, Any]:
        return self.transport.request("POST", f"/v1/simulation-sessions/{session_id}/actions", {
            "action": action, "parameters": parameters or {},
            "expected_version": expected_version, "call_id": call_id or uuid4().hex,
        })

    def submit(self, session_id: str, *, expected_version: int,
               call_id: str | None = None) -> dict[str, Any]:
        return self.transport.request("POST", f"/v1/simulation-sessions/{session_id}/submit", {
            "expected_version": expected_version, "call_id": call_id or uuid4().hex,
        })

    def events(self, session_id: str) -> dict[str, Any]:
        return self.transport.request("GET", f"/v1/simulation-sessions/{session_id}/events")


class CloudWorldFoundry:
    """WorldFoundry cloud client; provider details are never customer inputs."""
    DEFAULT_BASE_URL = "https://worldfoundry-api.vercel.app"

    def __init__(self, *, api_key: str, base_url: str | None = None):
        transport = HTTPTransport(base_url or self.DEFAULT_BASE_URL, api_key)
        self.projects = CloudResourceManager(transport, "projects")
        self.environments = CloudResourceManager(transport, "environments")
        self.templates = CloudResourceManager(transport, "templates")
        self.agents = CloudResourceManager(transport, "agents")
        self.scenarios = CloudResourceManager(transport, "scenarios")
        self.datasets = CloudResourceManager(transport, "datasets")
        self.policies = CloudResourceManager(transport, "policies")
        self.validators = CloudResourceManager(transport, "validators")
        self.tools = CloudResourceManager(transport, "tools")
        self.workflows = CloudResourceManager(transport, "workflows")
        self.applications = CloudResourceManager(transport, "applications")
        self.runs = CloudResourceManager(transport, "training-runs")
        self.training = CloudTrainingManager(transport)
        self.episodes = CloudResourceManager(transport, "episodes")
        self.simulations = CloudSimulationManager(transport)
        self.managed_runs = CloudManagedRuns(transport)
        self.artifacts = CloudArtifacts(transport)
        self.billing = CloudBilling(transport)
        self.connectors = CloudConnectors(transport)

class CloudTrainingManager(CloudResourceManager):
    def run_managed(self, **parameters: Any) -> dict[str, Any]:
        """Execute a bounded plan on a hosted environment."""
        return CloudManagedRuns(self.transport).create(**parameters)


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

