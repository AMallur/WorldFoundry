"""Episode engine shared by built-in and user-authored local workflow environments."""
from __future__ import annotations

import copy
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .declarative import DeclarativeEnvironment, apply_events, overlay, score_checks
from .environments import EnvironmentError
from .extensibility import TemplateRegistry
from .models import Episode, StepResult, ValidationResult
from .store import LocalStore


def _now() -> str:
    return datetime.now(UTC).isoformat()


class EpisodeEngine:
    """Local WorldFoundry engine with open-ended, explicitly registered templates."""

    def __init__(self, home: str | Path | None = None):
        self.store = LocalStore(home)
        self.templates = TemplateRegistry()
        self.templates.register("declarative", DeclarativeEnvironment,
                                description=DeclarativeEnvironment.description)

    def _environment_config(self, environment: str,
                            snapshot: dict[str, Any] | None = None
                            ) -> dict[str, Any]:
        if snapshot:
            return copy.deepcopy(snapshot)
        if environment.startswith("environment_"):
            manager = getattr(self, "environments", None)
            if manager is None:
                raise EnvironmentError("Custom environment requires a WorldFoundry client")
            resource = manager.get(environment)
            return {"template": resource.config["template"],
                    "settings": copy.deepcopy(resource.config.get("settings", {}))}
        # Backwards-compatible direct engine/CLI usage.
        template = "support-desk" if environment == "customer_support" else environment
        return {"template": template, "settings": {}}

    def _make_environment(self, config: dict[str, Any]) -> Any:
        return self.templates.make(config["template"], config.get("settings", {}))

    def environment_catalog(self) -> list[dict[str, Any]]:
        results = []
        for info in self.templates.list():
            try:
                env = self.templates.make(info["id"])
                tasks = list(env.tasks)
                actions = [action.to_dict() for action in env.actions()]
                name = env.name
                description = env.description
            except EnvironmentError:
                # A configurable factory may require explicit settings.
                tasks, actions = [], []
                name, description = info["id"], info["description"]
            results.append({"id": info["id"], "name": name,
                            "description": description, "tasks": tasks,
                            "actions": actions})
        return results

    def start(self, environment: str, task: str | None = None,
              seed: int = 0, *, scenario: dict[str, Any] | None = None) -> Episode:
        config = self._environment_config(environment)
        env = self._make_environment(config)
        scenario_config = copy.deepcopy(scenario or {})
        if not isinstance(scenario_config, dict):
            raise EnvironmentError("Scenario must be a JSON object")
        task_name = task or scenario_config.get("task") or env.tasks[0]
        if task_name not in env.tasks:
            raise EnvironmentError(
                f"Unknown task '{task_name}' for environment '{environment}'"
            )
        state = env.initial_state(seed)
        if not isinstance(state, dict):
            raise EnvironmentError("Environment initial_state must return a dictionary")
        state = overlay(state, scenario_config.get("state_overrides", {}))
        instruction = str(scenario_config.get("instruction", env.instruction))
        timestamp = _now()
        episode = Episode(
            id=f"ep_{uuid.uuid4().hex[:12]}",
            environment=environment,
            task=task_name,
            instruction=instruction,
            seed=seed,
            status="running",
            state=state,
            environment_config=config,
            scenario=scenario_config,
            created_at=timestamp,
            updated_at=timestamp,
        )
        episode.trace.append({
            "event_id": f"evt_{uuid.uuid4().hex}",
            "sequence": 0,
            "timestamp": timestamp,
            "type": "episode.started",
            "episode_id": episode.id,
            "environment": environment,
            "task": task_name,
            "seed": seed,
            "instruction": instruction,
        })
        # Fail before storing an episode if the custom configuration is not JSON.
        json.dumps(episode.to_dict(include_trace=True), allow_nan=False)
        self.store.save(episode)
        return episode

    def get(self, episode_id: str) -> Episode:
        return self.store.load(episode_id)

    def list_episodes(self) -> list[Episode]:
        return self.store.list()

    def available_actions(self, episode_id: str) -> list[str]:
        episode = self.get(episode_id)
        env = self._make_environment(
            self._environment_config(episode.environment, episode.environment_config)
        )
        return [action.name for action in env.actions()]

    def act(self, episode_id: str, action: str, **params: Any) -> StepResult:
        episode = self.get(episode_id)
        if episode.status != "running":
            raise EnvironmentError(f"Episode is {episode.status}; no more actions are allowed")
        env = self._make_environment(
            self._environment_config(episode.environment, episode.environment_config)
        )
        # Execute against a private clone so an invalid tool call cannot
        # partially corrupt persisted state or introduce inconsistent events.
        next_state = copy.deepcopy(episode.state)
        successful_steps = sum(event["type"] == "action.completed" for event in episode.trace)
        try:
            observation = env.perform(next_state, action, params)
            injected = apply_events(next_state, episode.scenario, successful_steps + 1)
            json.dumps(next_state, allow_nan=False)
        except Exception as exc:
            episode.updated_at = _now()
            episode.trace.append({
                "event_id": f"evt_{uuid.uuid4().hex}",
                "sequence": len(episode.trace),
                "timestamp": episode.updated_at,
                "type": "action.failed",
                "episode_id": episode.id,
                "action": action,
                "parameters": params,
                "error": str(exc) if isinstance(exc, EnvironmentError)
                         else type(exc).__name__,
            })
            self.store.save(episode)
            if isinstance(exc, EnvironmentError):
                raise
            raise EnvironmentError(
                f"Environment action raised {type(exc).__name__}"
            ) from exc
        episode.state = next_state
        episode.updated_at = _now()
        step_num = len(episode.trace)
        episode.trace.append({
            "event_id": f"evt_{uuid.uuid4().hex}",
            "sequence": len(episode.trace),
            "timestamp": episode.updated_at,
            "type": "action.completed",
            "episode_id": episode.id,
            "action": action,
            "parameters": params,
            "observation": observation,
        })
        for event in injected:
            episode.trace.append({
                **event,
                "event_id": f"evt_{uuid.uuid4().hex}",
                "sequence": len(episode.trace),
                "timestamp": episode.updated_at,
                "episode_id": episode.id,
            })
        self.store.save(episode)
        return StepResult(episode.id, action, observation, episode.status, step_num)

    def submit(self, episode_id: str) -> ValidationResult:
        episode = self.get(episode_id)
        if episode.status != "running":
            if episode.validation is None:
                raise EnvironmentError(f"Episode is {episode.status}")
            return episode.validation
        env = self._make_environment(
            self._environment_config(episode.environment, episode.environment_config)
        )
        checks = episode.scenario.get("checks")
        result = score_checks(episode.state, checks) if checks is not None else (
            env.validate(episode.state)
        )
        episode.validation = result
        episode.status = "passed" if result.passed else "failed"
        episode.updated_at = _now()
        episode.trace.append({
            "event_id": f"evt_{uuid.uuid4().hex}",
            "sequence": len(episode.trace),
            "timestamp": episode.updated_at,
            "type": "episode.submitted",
            "episode_id": episode.id,
            "status": episode.status,
            "validation": result.to_dict(),
        })
        self.store.save(episode)
        return result

    def export_trace(self, episode_id: str, path: str | Path) -> Path:
        return self.store.export_trace(episode_id, path)


# Preserve imports from the first local SDK release.
WorldFoundry = EpisodeEngine
