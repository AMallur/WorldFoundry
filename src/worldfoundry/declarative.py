"""Configurable, deterministic JSON-state environment and scenario operations.

Compatible with the hosted simulator's four state operations (read, set,
append, increment). This deliberately does not eval arbitrary expressions or
call out to external services.
"""
from __future__ import annotations

import copy
import json
import random
import re
from typing import Any

from .environments import EnvironmentError
from .models import ActionSpec, ValidationCheck, ValidationResult

MAX_STATE_BYTES = 65536
SEGMENT = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")
PROHIBITED = frozenset({"__proto__", "prototype", "constructor"})


def _size(value: Any) -> int:
    try:
        return len(json.dumps(value, allow_nan=False, separators=(",", ":")).encode())
    except (ValueError, TypeError) as exc:
        raise EnvironmentError("State/config must contain JSON-compatible finite values") from exc


def _parts(path: str, params: dict[str, Any]) -> list[str]:
    if not isinstance(path, str) or not 1 <= len(path) <= 256:
        raise EnvironmentError("Invalid state path")
    parts = []
    for token in path.split("."):
        part = params.get(token[1:]) if token.startswith("$") else token
        if not isinstance(part, str) or not SEGMENT.fullmatch(part) or part in PROHIBITED:
            raise EnvironmentError("Unsafe or missing path segment")
        parts.append(part)
    return parts


def at(state: dict[str, Any], path: str,
       params: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    parts = _parts(path, params or {})
    current: Any = state
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            raise EnvironmentError("Unknown state path")
        current = current[part]
    if not isinstance(current, dict) or parts[-1] not in current:
        raise EnvironmentError("Unknown state path")
    return current, parts[-1]


def transition(state: dict[str, Any], operation: str, path: str,
               value: Any = None, params: dict[str, Any] | None = None) -> Any:
    parent, key = at(state, path, params)
    if operation == "read":
        return copy.deepcopy(parent[key])
    if operation == "set":
        parent[key] = copy.deepcopy(value)
    elif operation == "append":
        if not isinstance(parent[key], list) or len(parent[key]) >= 1000:
            raise EnvironmentError("Append requires a list with fewer than 1000 entries")
        parent[key].append(copy.deepcopy(value))
    elif operation == "increment":
        if isinstance(parent[key], bool) or not isinstance(parent[key], (int, float)) or (
            isinstance(value, bool) or not isinstance(value, (int, float))
        ):
            raise EnvironmentError("Increment requires numbers")
        parent[key] += value
    else:
        raise EnvironmentError(f"Unsupported operation: {operation}")
    if _size(state) > MAX_STATE_BYTES:
        raise EnvironmentError("State exceeds 64 KiB limit")
    return copy.deepcopy(parent[key])


def overlay(state: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Pure, recursive overlay used to generate scenario variants."""
    if not isinstance(patch, dict):
        raise EnvironmentError("Scenario state_overrides must be an object")
    clone = copy.deepcopy(state)
    for key, val in patch.items():
        if key in PROHIBITED:
            raise EnvironmentError("Unsafe state override key")
        if isinstance(val, dict) and isinstance(clone.get(key), dict):
            clone[key] = overlay(clone[key], val)
        else:
            clone[key] = copy.deepcopy(val)
    if _size(clone) > MAX_STATE_BYTES:
        raise EnvironmentError("State exceeds 64 KiB limit")
    return clone


def seeded_scenario(config: dict[str, Any], seed: int) -> dict[str, Any]:
    """Select deterministic variations without changing the source config."""
    result = copy.deepcopy(config)
    variants = result.pop("variants", [])
    if variants:
        if not isinstance(variants, list) or len(variants) > 100 or not all(
            isinstance(variant, dict) for variant in variants
        ):
            raise EnvironmentError("Scenario variants must be a list of objects (max 100)")
        variation = copy.deepcopy(random.Random(seed).choice(variants))
        result.update(variation)
    return result


def apply_events(state: dict[str, Any], scenario: dict[str, Any],
                 step: int) -> list[dict[str, Any]]:
    events = scenario.get("events", [])
    if not isinstance(events, list) or len(events) > 64:
        raise EnvironmentError("Scenario events must be a list of at most 64 entries")
    observed = []
    for event in events:
        if not isinstance(event, dict) or not isinstance(event.get("at_step"), int):
            raise EnvironmentError("Invalid scenario event")
        if event["at_step"] == step:
            result = transition(state, event.get("operation", ""),
                                event.get("path", ""), event.get("value"))
            observed.append({"type": "scenario.event", "step": step,
                             "operation": event["operation"],
                             "path": event["path"], "result": result})
    return observed


def score_checks(state: dict[str, Any], checks: list[dict[str, Any]]) -> ValidationResult:
    if not isinstance(checks, list) or not 1 <= len(checks) <= 64:
        raise EnvironmentError("Scenario requires 1..64 evaluation checks")
    items: list[ValidationCheck] = []
    for check in checks:
        if not isinstance(check, dict) or not isinstance(check.get("name"), str):
            raise EnvironmentError("Check needs a name")
        op = check.get("operator", "eq")
        try:
            parent, key = at(state, check.get("path", ""))
            actual = parent[key]
            exists = True
        except EnvironmentError:
            actual, exists = None, False
        expected = check.get("equals", check.get("value"))
        if op == "exists":
            passed = exists
        elif op == "eq":
            passed = exists and actual == expected
        elif op == "ne":
            passed = exists and actual != expected
        elif op == "contains":
            passed = exists and isinstance(actual, (str, list, dict)) and expected in actual
        elif op in {"gt", "gte", "lt", "lte"}:
            valid = all(isinstance(v, (int, float)) and not isinstance(v, bool)
                        for v in (actual, expected))
            passed = valid and {"gt": lambda: actual > expected,
                                "gte": lambda: actual >= expected,
                                "lt": lambda: actual < expected,
                                "lte": lambda: actual <= expected}[op]()
        else:
            raise EnvironmentError(f"Unsupported check operator: {op}")
        items.append(ValidationCheck(check["name"], bool(passed),
                                     check.get("message", check["name"])))
    total = sum(item.passed for item in items)
    return ValidationResult(total == len(items), total / len(items), tuple(items))


class DeclarativeEnvironment:
    """User-authored environment requiring no Python subclass or code execution."""

    id = "declarative"
    name = "Declarative Environment"
    description = "JSON-configured state, tools, seeded variants and evaluators."

    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = copy.deepcopy(settings)
        initial = self.settings.get("initial_state")
        actions = self.settings.get("actions")
        if not isinstance(initial, dict) or not isinstance(actions, dict) or not actions:
            raise EnvironmentError("Declarative template needs initial_state and actions")
        if len(actions) > 64 or _size(initial) > MAX_STATE_BYTES:
            raise EnvironmentError("Environment exceeds configured size/action limits")
        self.name = str(settings.get("name", self.name))
        self.description = str(settings.get("description", self.description))
        self.instruction = str(settings.get("instruction", "Complete the requested workflow."))
        self.tasks = (str(settings.get("task", "default")),)
        definitions: list[ActionSpec] = []
        for name, spec in actions.items():
            if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name):
                raise EnvironmentError("Invalid action name")
            if not isinstance(spec, dict) or spec.get("operation") not in (
                "read", "set", "append", "increment"
            ):
                raise EnvironmentError(f"Invalid action definition: {name}")
            _parts(spec.get("path", ""), {
                part[1:]: "safe" for part in str(spec.get("path", "")).split(".")
                if part.startswith("$")
            })
            params = spec.get("parameters", {})
            if not isinstance(params, dict) or len(params) > 16:
                raise EnvironmentError("Action parameter schemas must be objects (max 16)")
            definitions.append(ActionSpec(
                name, str(spec.get("description", name)), params, tuple(params)
            ))
        self._actions = tuple(definitions)

    def initial_state(self, seed: int) -> dict[str, Any]:
        state = copy.deepcopy(self.settings["initial_state"])
        variants = self.settings.get("variants", [])
        if variants:
            if not isinstance(variants, list) or len(variants) > 100:
                raise EnvironmentError("Environment variants must be a list (max 100)")
            state = overlay(state, random.Random(seed).choice(variants))
        return state

    def actions(self) -> tuple[ActionSpec, ...]:
        return self._actions

    def perform(self, state: dict[str, Any], action: str,
                params: dict[str, Any]) -> dict[str, Any]:
        definition = self.settings["actions"].get(action)
        if definition is None:
            raise EnvironmentError(f"Unknown action: {action}")
        spec = next(item for item in self._actions if item.name == action)
        if set(params) != set(spec.required):
            raise EnvironmentError("Missing or unexpected action parameters")
        for name, rule in spec.parameters.items():
            actual = params[name]
            kind = rule.get("type")
            correct = (kind == "string" and isinstance(actual, str)
                       or kind == "number" and isinstance(actual, (int, float))
                       and not isinstance(actual, bool)
                       or kind == "boolean" and isinstance(actual, bool)
                       or kind == "object" and isinstance(actual, dict))
            if not correct or "enum" in rule and actual not in rule["enum"]:
                raise EnvironmentError(f"Invalid parameter: {name}")
        value = params[definition["from_param"]] if definition.get("from_param") else (
            definition.get("value")
        )
        result = transition(state, definition["operation"], definition["path"], value, params)
        return {"result": result}

    def validate(self, state: dict[str, Any]) -> ValidationResult:
        return score_checks(state, self.settings.get("checks", [
            {"name": "valid_state", "path": next(iter(state)), "operator": "exists"},
        ]))
