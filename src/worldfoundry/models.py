from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ActionSpec:
    name: str
    description: str
    parameters: dict[str, dict[str, Any]]
    required: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["required"] = list(self.required)
        return data


@dataclass(frozen=True)
class ValidationCheck:
    name: str
    passed: bool
    message: str


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    score: float
    checks: tuple[ValidationCheck, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "score": self.score,
            "checks": [asdict(check) for check in self.checks],
        }


@dataclass
class Episode:
    id: str
    environment: str
    task: str
    instruction: str
    seed: int
    status: str
    state: dict[str, Any]
    trace: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    validation: ValidationResult | None = None

    def to_dict(self, *, include_state: bool = True, include_trace: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "environment": self.environment,
            "task": self.task,
            "instruction": self.instruction,
            "seed": self.seed,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "validation": self.validation.to_dict() if self.validation else None,
        }
        if include_state:
            data["state"] = self.state
        if include_trace:
            data["trace"] = self.trace
        return data


@dataclass(frozen=True)
class StepResult:
    episode_id: str
    action: str
    observation: dict[str, Any]
    status: str
    step: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

