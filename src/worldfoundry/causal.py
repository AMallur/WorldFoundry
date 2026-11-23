"""Budgeted, reproducible failure-boundary discovery for existing WorldFoundry agents.

No external dependencies. This module discovers *associations under controlled
scenario interventions*; it does not claim to identify latent causal mechanisms.
"""
from __future__ import annotations

import copy
import itertools
import json
import math
import random
from dataclasses import dataclass, asdict
from typing import Any, Callable, Mapping, Sequence


@dataclass(frozen=True)
class Factor:
    """A single independently controllable scenario field.

    path is a dotted path within a scenario's state_overrides object.
    Values must be JSON-compatible. baseline must occur in values.
    """
    path: str
    baseline: Any
    values: tuple[Any, ...]

    def __post_init__(self) -> None:
        if not self.path or any(not p.isidentifier() or p.startswith("_") for p in self.path.split(".")):
            raise ValueError("Factor paths must be simple dotted identifiers")
        if not self.values or self.baseline not in self.values:
            raise ValueError("Factor baseline must appear in nonempty values")
        for value in self.values:
            json.dumps(value, allow_nan=False)


@dataclass(frozen=True)
class Boundary:
    changes: dict[str, Any]
    baseline_failures: int
    variant_failures: int
    trials: int
    baseline_failure_rate: float
    variant_failure_rate: float
    risk_difference: float
    lower_bound: float
    upper_bound: float


@dataclass
class Discovery:
    boundaries: list[Boundary]
    evaluations: int
    scenarios: int
    budget: int
    seed: int
    baseline_failure_rate: float
    skipped_candidates: int

    def to_dict(self) -> dict[str, Any]:
        return {"boundaries": [asdict(b) for b in self.boundaries],
                "evaluations": self.evaluations, "scenarios": self.scenarios,
                "budget": self.budget, "seed": self.seed,
                "baseline_failure_rate": self.baseline_failure_rate,
                "skipped_candidates": self.skipped_candidates}


def _patch(changes: Mapping[str, Any]) -> dict[str, Any]:
    root: dict[str, Any] = {}
    for path, value in changes.items():
        node = root
        for part in path.split(".")[:-1]:
            node = node.setdefault(part, {})
        node[path.split(".")[-1]] = copy.deepcopy(value)
    return root


def _wilson(failures: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = failures / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0., center - margin), min(1., center + margin)


def discover(
    evaluate: Callable[[dict[str, Any], int], bool],
    factors: Sequence[Factor],
    *,
    budget: int = 100,
    trials: int = 5,
    seed: int = 0,
    min_risk_increase: float = 0.5,
    max_order: int = 2,
    valid: Callable[[dict[str, Any]], bool] | None = None,
) -> Discovery:
    """Find small scenario interventions associated with increased failure.

    evaluate(overrides, seed) returns True on agent success, False on failure.
    Both baseline and variant receive identical trial seeds (common random
    numbers); stochastic model APIs may not honor seeds. A candidate counts
    only if its observed failure rate exceeds baseline by min_risk_increase.
    Wilson bounds are descriptive, not a paired causal confidence interval.
    Search stops before exceeding the total evaluation budget. No LLM calls
    or external writes are performed by this function.
    """
    if budget < 2 or trials < 1 or not 0 < min_risk_increase <= 1:
        raise ValueError("Invalid budget, trials, or minimum risk increase")
    if max_order < 1 or not factors:
        raise ValueError("Need factors and max_order >= 1")
    paths = [f.path for f in factors]
    if len(set(paths)) != len(paths):
        raise ValueError("Duplicate factor paths")
    if any(a.startswith(b + ".") or b.startswith(a + ".")
           for a, b in itertools.combinations(paths, 2)):
        raise ValueError("Overlapping factor paths")
    if budget < 2 * trials:
        raise ValueError("Budget must allow baseline and one candidate at requested trials")

    rng = random.Random(seed)
    trial_seeds = [rng.randrange(2**31) for _ in range(trials)]
    baseline = {f.path: f.baseline for f in factors}
    base_patch = _patch(baseline)
    if valid is not None and not valid(copy.deepcopy(base_patch)):
        raise ValueError("Baseline violates validity constraints")
    base_failures = sum(not bool(evaluate(copy.deepcopy(base_patch), s)) for s in trial_seeds)
    used, scenarios, skipped = trials, 1, 0
    boundaries: list[Boundary] = []
    # Prioritize single-variable boundaries before interaction candidates.
    for order in range(1, min(max_order, len(factors)) + 1):
        for subset in itertools.combinations(factors, order):
            choices = [[v for v in f.values if v != f.baseline] for f in subset]
            for values in itertools.product(*choices):
                changes = {f.path: v for f, v in zip(subset, values)}
                candidate = {**baseline, **changes}
                patch = _patch(candidate)
                if valid is not None and not valid(copy.deepcopy(patch)):
                    skipped += 1
                    continue
                if used + trials > budget:
                    return Discovery(boundaries, used, scenarios, budget, seed,
                                     base_failures / trials, skipped)
                failures = sum(not bool(evaluate(copy.deepcopy(patch), s))
                               for s in trial_seeds)
                used += trials
                scenarios += 1
                difference = (failures - base_failures) / trials
                if difference >= min_risk_increase:
                    lo1, hi1 = _wilson(failures, trials)
                    lo0, hi0 = _wilson(base_failures, trials)
                    boundaries.append(Boundary(
                        changes, base_failures, failures, trials,
                        base_failures / trials, failures / trials, difference,
                        max(-1., lo1 - hi0), min(1., hi1 - lo0)))
    return Discovery(boundaries, used, scenarios, budget, seed,
                     base_failures / trials, skipped)


def worldfoundry_evaluator(wf: Any, agent: Any, environment: Any,
                           *, task: str | None = None, max_steps: int = 30
                           ) -> Callable[[dict[str, Any], int], bool]:
    """Adapt an already-registered local callable agent to boundary discovery.

    Each evaluation creates a fresh episode. Agent exceptions count as failure;
    environment/infrastructure errors propagate. This is deliberately local.
    """
    from .platform import AgentTools
    if agent.id not in wf.agents.handlers:
        raise ValueError("Agent must be registered in this WorldFoundry process")
    handler = wf.agents.handlers[agent.id]

    def evaluate(overrides: dict[str, Any], seed: int) -> bool:
        episode = wf.start(environment.id, task=task, seed=seed,
                           scenario={"state_overrides": overrides})
        tools = AgentTools(wf, episode.id, max_steps)
        failed = False
        try:
            handler(episode.instruction, tools)
        except Exception:
            failed = True
        result = wf.submit(episode.id)
        return bool(result.passed) and not failed

    return evaluate
