"""Local agent execution and resource managers for the public SDK."""
from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .engine import EpisodeEngine
from .environments import get_environment


class WorldFoundryError(Exception):
    pass


@dataclass(frozen=True)
class Resource:
    id: str
    name: str
    kind: str
    config: dict[str, Any]


class Registry:
    def __init__(self, root: Path):
        self.root = root / "resources"

    def put(self, resource: Resource) -> Resource:
        folder = self.root / resource.kind
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{resource.id}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(resource.__dict__, indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)
        return resource

    def get(self, kind: str, resource_id: str) -> Resource:
        if not resource_id.startswith(f"{kind}_") or "/" in resource_id:
            raise WorldFoundryError(f"Invalid {kind} ID")
        target = self.root / kind / f"{resource_id}.json"
        if not target.exists():
            raise WorldFoundryError(f"Unknown {kind}: {resource_id}")
        return Resource(**json.loads(target.read_text(encoding="utf-8")))

    def list(self, kind: str) -> list[Resource]:
        folder = self.root / kind
        if not folder.exists():
            return []
        return [self.get(kind, path.stem) for path in sorted(folder.glob("*.json"))]


class ResourceManager:
    def __init__(self, registry: Registry, kind: str):
        self.registry = registry
        self.kind = kind

    def create(self, name: str | None = None, **config: Any) -> Resource:
        name = name or config.get("template") or self.kind
        resource = Resource(f"{self.kind}_{uuid.uuid4().hex[:12]}", name, self.kind, config)
        return self.registry.put(resource)

    def get(self, resource_id: str) -> Resource:
        return self.registry.get(self.kind, resource_id)

    def list(self) -> list[Resource]:
        return self.registry.list(self.kind)


class EnvironmentManager(ResourceManager):
    def create(self, *, template: str, difficulty: str = "beginner", name: str | None = None,
               config: dict[str, Any] | None = None) -> Resource:
        aliases = {"customer_support": "support-desk", "support-desk": "support-desk"}
        if template not in aliases:
            raise WorldFoundryError(f"Unknown environment template: {template}")
        if difficulty != "beginner":
            raise WorldFoundryError("Only beginner difficulty is implemented in the support desk template")
        return super().create(name=name or template, template=aliases[template],
                              difficulty=difficulty, settings=config or {})


class AgentTools:
    def __init__(self, engine: EpisodeEngine, episode_id: str, max_steps: int):
        self.engine = engine
        self.episode_id = episode_id
        self.submitted = False
        self.max_steps = max_steps
        self.steps = 0

    def act(self, action: str, **parameters: Any) -> dict[str, Any]:
        if self.submitted:
            raise WorldFoundryError("Agent already submitted this episode")
        if self.steps >= self.max_steps:
            raise WorldFoundryError("Episode action budget exceeded")
        self.steps += 1
        return self.engine.act(self.episode_id, action, **parameters).observation

    def submit(self) -> None:
        self.submitted = True

    def __getattr__(self, action: str) -> Callable[..., dict[str, Any]]:
        names = {item.name for item in get_environment("support-desk").actions()}
        if action not in names:
            raise AttributeError(action)
        return lambda **parameters: self.act(action, **parameters)


class AgentManager(ResourceManager):
    def __init__(self, registry: Registry):
        super().__init__(registry, "agent")
        self.handlers: dict[str, Callable[..., Any]] = {}

    def register(self, *, name: str, handler: Callable[..., Any] | None = None,
                 framework: str = "python", endpoint: str | None = None) -> Resource:
        if (handler is None) == (endpoint is None):
            raise WorldFoundryError("Provide exactly one handler or endpoint")
        if endpoint:
            raise WorldFoundryError("Remote agent endpoints are not executable in this local release")
        if framework != "python":
            raise WorldFoundryError("Use framework='python' for local callables; ADK runner is pending")
        resource = self.create(name=name, framework=framework, invocation="python_callable")
        self.handlers[resource.id] = handler  # live Python objects intentionally stay in process
        return resource


@dataclass
class TrainingRun:
    id: str
    status: str
    episode_ids: list[str]
    scores: list[float]
    report_path: Path
    report_url: str | None = None

    @property
    def success_rate(self) -> float:
        return sum(score == 1.0 for score in self.scores) / len(self.scores) if self.scores else 0.0

    @property
    def summary(self) -> dict[str, Any]:
        return {"id": self.id, "status": self.status, "episodes": len(self.episode_ids),
                "success_rate": self.success_rate, "mean_score": sum(self.scores) / len(self.scores)}

    def wait(self) -> TrainingRun:
        return self  # local execution currently completes before returning


class TrainingManager:
    def __init__(self, engine: EpisodeEngine, agents: AgentManager, registry: Registry):
        self.engine, self.agents, self.registry = engine, agents, registry

    def create(self, *, agent: Resource, environment: Resource, episodes: int = 1,
               concurrency: int = 1, max_steps: int = 30, seed: int = 0) -> TrainingRun:
        if not 1 <= episodes <= 10000 or concurrency != 1 or not 1 <= max_steps <= 1000:
            raise WorldFoundryError("episodes, concurrency, and max_steps must be within supported limits")
        if agent.id not in self.agents.handlers:
            raise WorldFoundryError("Local callable is not registered in this process")
        environment = self.registry.get("environment", environment.id)
        template = environment.config["template"]
        handler = self.agents.handlers[agent.id]
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        ids: list[str] = []
        scores: list[float] = []
        failures: list[str | None] = []
        for index in range(episodes):
            episode = self.engine.start(template, seed=seed + index)
            ids.append(episode.id)
            tools = AgentTools(self.engine, episode.id, max_steps)
            error = None
            try:
                handler(episode.instruction, tools)
            except Exception as exc:  # noqa: BLE001 - user supplied agent must not abort the batch
                error = f"{type(exc).__name__}: {exc}"
            result = self.engine.submit(episode.id)
            scores.append(result.score)
            failures.append(error)
        run = TrainingRun(run_id, "completed", ids, scores,
                          self.registry.root.parent / "runs" / run_id / "report.json")
        run.report_path.parent.mkdir(parents=True, exist_ok=True)
        run.report_path.write_text(json.dumps({**run.summary, "episode_ids": ids,
                                               "scores": scores, "agent_errors": failures}, indent=2) + "\n")
        return run

