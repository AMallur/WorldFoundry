from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .environments import ENVIRONMENTS, EnvironmentError, get_environment
from .models import Episode, StepResult, ValidationResult
from .store import LocalStore


def _now() -> str:
    return datetime.now(UTC).isoformat()


class EpisodeEngine:
    """Local WorldFoundry client and episode engine."""

    def __init__(self, home: str | Path | None = None):
        self.store = LocalStore(home)

    def environment_catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "id": env.id,
                "name": env.name,
                "description": env.description,
                "tasks": list(env.tasks),
                "actions": [action.to_dict() for action in env.actions()],
            }
            for env in ENVIRONMENTS.values()
        ]

    def start(self, environment: str, task: str = "incident-triage", seed: int = 0) -> Episode:
        env = get_environment(environment)
        if task not in env.tasks:
            raise EnvironmentError(f"Unknown task '{task}' for environment '{environment}'")
        timestamp = _now()
        episode = Episode(
            id=f"ep_{uuid.uuid4().hex[:12]}",
            environment=environment,
            task=task,
            instruction=env.instruction,
            seed=seed,
            status="running",
            state=env.initial_state(seed),
            created_at=timestamp,
            updated_at=timestamp,
        )
        episode.trace.append(
            {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "sequence": 0,
                "timestamp": timestamp,
                "type": "episode.started",
                "episode_id": episode.id,
                "environment": environment,
                "task": task,
                "seed": seed,
                "instruction": episode.instruction,
            }
        )
        self.store.save(episode)
        return episode

    def get(self, episode_id: str) -> Episode:
        return self.store.load(episode_id)

    def list_episodes(self) -> list[Episode]:
        return self.store.list()

    def act(self, episode_id: str, action: str, **params: Any) -> StepResult:
        episode = self.get(episode_id)
        if episode.status != "running":
            raise EnvironmentError(f"Episode is {episode.status}; no more actions are allowed")
        env = get_environment(episode.environment)
        try:
            observation = env.perform(episode.state, action, params)
        except EnvironmentError as exc:
            episode.updated_at = _now()
            episode.trace.append(
                {
                    "event_id": f"evt_{uuid.uuid4().hex}",
                    "sequence": len(episode.trace),
                    "timestamp": episode.updated_at,
                    "type": "action.failed",
                    "episode_id": episode.id,
                    "action": action,
                    "parameters": params,
                    "error": str(exc),
                }
            )
            self.store.save(episode)
            raise
        episode.updated_at = _now()
        episode.trace.append(
            {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "sequence": len(episode.trace),
                "timestamp": episode.updated_at,
                "type": "action.completed",
                "episode_id": episode.id,
                "action": action,
                "parameters": params,
                "observation": observation,
            }
        )
        self.store.save(episode)
        return StepResult(episode.id, action, observation, episode.status, len(episode.trace) - 1)

    def submit(self, episode_id: str) -> ValidationResult:
        episode = self.get(episode_id)
        if episode.status != "running":
            if episode.validation is None:
                raise EnvironmentError(f"Episode is {episode.status}")
            return episode.validation
        result = get_environment(episode.environment).validate(episode.state)
        episode.validation = result
        episode.status = "passed" if result.passed else "failed"
        episode.updated_at = _now()
        episode.trace.append(
            {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "sequence": len(episode.trace),
                "timestamp": episode.updated_at,
                "type": "episode.submitted",
                "episode_id": episode.id,
                "status": episode.status,
                "validation": result.to_dict(),
            }
        )
        self.store.save(episode)
        return result

    def export_trace(self, episode_id: str, path: str | Path) -> Path:
        return self.store.export_trace(episode_id, path)


# Preserve imports from the first local SDK release.
WorldFoundry = EpisodeEngine

