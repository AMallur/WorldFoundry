"""Local agent execution and resource managers for the public SDK."""
from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .declarative import seeded_scenario
from .engine import EpisodeEngine
from .extensibility import TemplateRegistry


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
    """Register custom local Python templates or JSON-configured environments."""

    def __init__(self, registry: Registry, templates: TemplateRegistry):
        super().__init__(registry, "environment")
        self.templates = templates

    def register_template(self, name: str, factory: Any, *,
                          description: str = "", replace: bool = False) -> None:
        """Register a trusted environment object or factory in this process."""
        self.templates.register(name, factory, description=description, replace=replace)

    def create(self, *, template: str, difficulty: str = "beginner",
               name: str | None = None, config: dict[str, Any] | None = None) -> Resource:
        aliases = {"customer_support": "support-desk", "support-desk": "support-desk"}
        chosen = aliases.get(template, template)
        if chosen == "support-desk" and difficulty != "beginner":
            raise WorldFoundryError("Only beginner difficulty is implemented in the support desk template")
        settings = config or {}
        if not isinstance(settings, dict):
            raise TypeError("Environment config must be a JSON object")
        # Validate before persisting metadata. Secrets and Python handlers must
        # live in the user-authored factory, never in the settings JSON.
        self.templates.make(chosen, settings)
        return super().create(name=name or chosen, template=chosen,
                              difficulty=difficulty, settings=settings)

    def from_file(self, file: str | Path) -> Resource:
        """Load a customer-owned declarative environment definition from JSON."""
        raw = json.loads(Path(file).read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("config"), dict):
            raise WorldFoundryError("Environment JSON needs a config object")
        return self.create(template=raw.get("template", "declarative"),
                           name=raw.get("name"), config=raw["config"])

    def configure(self, resource_id: str, config: dict[str, Any]) -> Resource:
        """Update future episode settings; active episodes keep their snapshots."""
        existing = self.get(resource_id)
        if not isinstance(config, dict):
            raise TypeError("Environment config must be a JSON object")
        self.templates.make(existing.config["template"], config)
        updated = Resource(existing.id, existing.name, existing.kind,
                           {**existing.config, "settings": config})
        return self.registry.put(updated)


class ScenarioManager(ResourceManager):
    """User-defined scenarios with optional trusted, seed-driven Python generators."""

    def __init__(self, registry: Registry):
        super().__init__(registry, "scenario")
        self.generators: dict[str, Callable[[int, dict[str, Any]], dict[str, Any]]] = {}

    def register_generator(self, name: str,
                           generator: Callable[[int, dict[str, Any]], dict[str, Any]]) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name) or not callable(generator):
            raise WorldFoundryError("Invalid scenario generator name or function")
        if name in self.generators:
            raise WorldFoundryError(f"Scenario generator already registered: {name}")
        self.generators[name] = generator

    def prepare(self, scenario: Resource, seed: int) -> dict[str, Any]:
        stored = self.get(scenario.id)
        config = dict(stored.config)
        generator_name = config.pop("generator", None)
        if generator_name is not None:
            if generator_name not in self.generators:
                raise WorldFoundryError(f"Generator not registered: {generator_name}")
            generated = self.generators[generator_name](seed, dict(config))
            if not isinstance(generated, dict):
                raise WorldFoundryError("Scenario generator must return a JSON object")
            config.update(generated)
        return seeded_scenario(config, seed)


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
        names = set(self.engine.available_actions(self.episode_id))
        if action not in names:
            raise AttributeError(action)
        return lambda **parameters: self.act(action, **parameters)


class AgentManager(ResourceManager):
    def __init__(self, registry: Registry):
        super().__init__(registry, "agent")
        self.handlers: dict[str, Callable[..., Any]] = {}

    def register(self, *, name: str, handler: Callable[..., Any] | None = None,
                 framework: str = "python", endpoint: str | None = None,
                 adapter: Any | None = None) -> Resource:
        if sum(value is not None for value in (handler, endpoint, adapter)) != 1:
            raise WorldFoundryError("Provide exactly one handler, adapter or endpoint")
        if adapter is not None:
            handler = getattr(adapter, "run", None)
            if not callable(handler):
                raise WorldFoundryError("Agent adapter must implement run(instruction, tools)")
        if endpoint:
            raise WorldFoundryError("Remote agent endpoints are not executable in this local release")
        if framework != "python":
            raise WorldFoundryError("Use framework='python' for local callables; ADK runner is pending")
        resource = self.create(name=name, framework=framework, invocation="python_callable")
        self.handlers[resource.id] = handler  # local callable stays in this process
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
    def __init__(self, engine: EpisodeEngine, agents: AgentManager, registry: Registry,
                 scenarios: ScenarioManager):
        self.engine, self.agents, self.registry = engine, agents, registry
        self.scenarios = scenarios

    def create(self, *, agent: Resource, environment: Resource, episodes: int = 1,
               concurrency: int = 1, max_steps: int = 30, seed: int = 0,
               scenario: Resource | None = None, task: str | None = None) -> TrainingRun:
        if not 1 <= episodes <= 10000 or concurrency != 1 or not 1 <= max_steps <= 1000:
            raise WorldFoundryError("episodes, concurrency, and max_steps must be within supported limits")
        if agent.id not in self.agents.handlers:
            raise WorldFoundryError("Local callable is not registered in this process")
        environment = self.registry.get("environment", environment.id)
        handler = self.agents.handlers[agent.id]
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        ids: list[str] = []
        scores: list[float] = []
        failures: list[str | None] = []
        for index in range(episodes):
            scenario_config = self.scenarios.prepare(scenario, seed + index) if scenario else None
            episode = self.engine.start(environment.id, task=task, seed=seed + index,
                                        scenario=scenario_config)
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

