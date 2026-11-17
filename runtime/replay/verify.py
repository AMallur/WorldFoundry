"""Replay a scripted training experience and confirm its event stream is stable."""
from __future__ import annotations

from typing import Any

from runtime.scripted import run_plan


def replay_identical(env: dict[str, Any], scenario: dict[str, Any],
                     plan: list[dict[str, Any]], seed: int,
                     expected_trace: list[dict[str, Any]]) -> bool:
    result = run_plan(env, scenario, plan, seed=seed)
    return result.events == expected_trace
