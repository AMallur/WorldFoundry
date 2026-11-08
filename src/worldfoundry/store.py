from __future__ import annotations

import json
import os
from pathlib import Path

from .models import Episode, ValidationCheck, ValidationResult


class EpisodeNotFound(KeyError):
    pass


class LocalStore:
    def __init__(self, root: str | Path | None = None):
        configured = root or os.environ.get("WORLDFOUNDRY_HOME")
        self.root = Path(configured).expanduser() if configured else Path.home() / ".worldfoundry"
        self.episodes_dir = self.root / "episodes"

    def save(self, episode: Episode) -> None:
        self.episodes_dir.mkdir(parents=True, exist_ok=True)
        path = self.episodes_dir / f"{episode.id}.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(episode.to_dict(include_trace=True), indent=2) + "\n", encoding="utf-8")
        temp.replace(path)

    def load(self, episode_id: str) -> Episode:
        path = self.episodes_dir / f"{episode_id}.json"
        if not path.exists():
            raise EpisodeNotFound(episode_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        validation = None
        if data.get("validation"):
            raw = data["validation"]
            validation = ValidationResult(
                raw["passed"],
                raw["score"],
                tuple(ValidationCheck(**check) for check in raw["checks"]),
            )
        return Episode(
            id=data["id"],
            environment=data["environment"],
            task=data["task"],
            instruction=data["instruction"],
            seed=data["seed"],
            status=data["status"],
            state=data["state"],
            trace=data.get("trace", []),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            validation=validation,
        )

    def list(self) -> list[Episode]:
        if not self.episodes_dir.exists():
            return []
        return [self.load(path.stem) for path in sorted(self.episodes_dir.glob("*.json"))]

    def export_trace(self, episode_id: str, path: str | Path) -> Path:
        episode = self.load(episode_id)
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        lines = (json.dumps(event, sort_keys=True) for event in episode.trace)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return target

