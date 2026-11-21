"""Evidence-backed, local-only business workflow simulations.

This module never calls customer systems or infers hidden business behavior as fact.
It implements explicit, executable rules and compares them with recorded reference
outcomes. All customer connectors remain opt-in and read-only by default.
"""
from __future__ import annotations

import copy
import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .declarative import MAX_STATE_BYTES, _size, at, overlay, score_checks, transition
from .environments import EnvironmentError
from .models import ActionSpec, ValidationResult

ACTION_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
PRIVATE_KEYS = frozenset({
    "password", "passwd", "secret", "access_token", "refresh_token",
    "authorization", "api_key", "private_key", "client_secret",
})


def _validate_evidence(value: Any) -> Any:
    """Reject credentials, unsafe JSON and oversized data before persisting."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Evidence object keys must be strings")
            if key.lower().replace("-", "_") in PRIVATE_KEYS:
                raise ValueError("Evidence includes a credential field")
            _validate_evidence(item)
    elif isinstance(value, list):
        for item in value:
            _validate_evidence(item)
    elif not (value is None or isinstance(value, (str, int, float, bool))):
        raise ValueError("Evidence must contain JSON-compatible values")
    try:
        if len(json.dumps(value, allow_nan=False, separators=(",", ":")).encode()) > 262144:
            raise ValueError("Evidence exceeds 256 KiB")
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid or oversized JSON evidence") from exc
    return value


@dataclass(frozen=True)
class ReferenceCase:
    """An authorized, recorded before/action/after test case."""

    action: str
    before: dict[str, Any]
    after: dict[str, Any]
    parameters: dict[str, Any] = field(default_factory=dict)
    response: dict[str, Any] | None = None
    case_id: str = ""
    source: str = "user-supplied reference"

    def __post_init__(self) -> None:
        if not ACTION_RE.fullmatch(self.action):
            raise ValueError("Invalid reference action name")
        for value in (self.before, self.after, self.parameters):
            if not isinstance(value, dict):
                raise ValueError("Reference states and parameters must be objects")
            _validate_evidence(value)
        if self.response is not None:
            if not isinstance(self.response, dict):
                raise ValueError("Reference response must be an object")
            _validate_evidence(self.response)


def _differences(expected: Any, actual: Any, path: str = "$") -> list[dict[str, Any]]:
    """Structural JSON comparison: preserve types, including bool versus int."""
    if type(expected) is not type(actual):
        return [{"path": path, "expected": expected, "actual": actual}]
    if isinstance(expected, dict):
        differences: list[dict[str, Any]] = []
        for key in sorted(set(expected) | set(actual)):
            child = path + "." + str(key)
            if key not in expected or key not in actual:
                differences.append({"path": child,
                                    "expected": expected.get(key, "<missing>"),
                                    "actual": actual.get(key, "<missing>")})
            else:
                differences.extend(_differences(expected[key], actual[key], child))
        return differences
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return [{"path": path, "expected": expected, "actual": actual}]
        differences = []
        for index, (left, right) in enumerate(zip(expected, actual)):
            differences.extend(_differences(left, right, f"{path}[{index}]"))
        return differences
    return [] if expected == actual else [
        {"path": path, "expected": expected, "actual": actual}
    ]


def _changed_leaves(before: Any, after: Any, prefix: str = "") -> dict[str, Any]:
    """Infer only updates of *existing* scalar fields, not CRUD or hidden effects."""
    if type(before) is not type(after):
        return {prefix: copy.deepcopy(after)} if prefix else {}
    if isinstance(before, dict):
        changes: dict[str, Any] = {}
        if set(before) != set(after):
            raise ValueError("Schema changed; automatic reconstruction cannot infer CRUD")
        for key in before:
            if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", key):
                raise ValueError("Unsafe state key")
            changes.update(_changed_leaves(before[key], after[key],
                                           f"{prefix}.{key}" if prefix else key))
        return changes
    if isinstance(before, list):
        if before != after:
            raise ValueError("List changes require an explicit rule")
        return {}
    return {prefix: copy.deepcopy(after)} if before != after else {}


def propose_actions(cases: Sequence[ReferenceCase], *,
                    min_cases: int = 2) -> dict[str, Any]:
    """Produce *unapproved* candidate rules supported by consistent examples.

    This can infer constant assignments or values copied from action parameters.
    It deliberately cannot infer permissions, conditional branches, side effects,
    timing, unobserved exceptions, or real-world causality.
    """
    if min_cases < 2:
        raise ValueError("At least two independent observations are required")
    groups: dict[str, list[ReferenceCase]] = defaultdict(list)
    for case in cases:
        groups[case.action].append(case)
    actions: dict[str, Any] = {}
    rejected: dict[str, str] = {}
    for name, examples in groups.items():
        if len(examples) < min_cases:
            rejected[name] = "Insufficient reference cases"
            continue
        try:
            changed = [_changed_leaves(case.before, case.after) for case in examples]
            if not changed[0] or any(set(delta) != set(changed[0]) for delta in changed):
                raise ValueError("Inconsistent or absent changed fields")
            if any(set(case.parameters) != set(examples[0].parameters)
                   for case in examples):
                raise ValueError("Parameter sets differ")
            effects = []
            for path in changed[0]:
                values = [delta[path] for delta in changed]
                parameter = next((param for param in examples[0].parameters
                                  if all(case.parameters[param] == value
                                         for case, value in zip(examples, values))), None)
                if parameter:
                    effects.append({"operation": "set", "path": path,
                                    "from_param": parameter})
                elif all(type(value) is type(values[0]) and value == values[0]
                         for value in values):
                    effects.append({"operation": "set", "path": path,
                                    "value": values[0]})
                else:
                    raise ValueError("Changing output cannot be explained by parameters")
            schemas: dict[str, dict[str, Any]] = {}
            for param, sample in examples[0].parameters.items():
                if all(type(case.parameters[param]) is type(sample) for case in examples):
                    kind = ("boolean" if isinstance(sample, bool) else
                            "string" if isinstance(sample, str) else
                            "number" if isinstance(sample, (int, float)) else
                            "object" if isinstance(sample, dict) else None)
                    if kind is None:
                        raise ValueError("Unsupported parameter type")
                    schemas[param] = {"type": kind}
                else:
                    raise ValueError("Parameter types differ")
            actions[name] = {"parameters": schemas, "effects": effects}
        except (ValueError, EnvironmentError) as exc:
            rejected[name] = str(exc)
    return {
        "status": "draft_requires_verification",
        "actions": actions,
        "rejected": rejected,
        "limitations": [
            "No permission rules, error branches, or cross-system effects inferred",
            "Run independent held-out tests and obtain human approval before use",
        ],
    }


class RealityEnvironment:
    """Stateful, transactional, evidence-verifiable business workflow template.

    Explicit guards and multiple ordered effects are evaluated atomically.
    WorldFoundry's EpisodeEngine provides a second copy-on-write state boundary.
    """

    id = "reality"
    name = "Reality Workflow"
    description = "Explicit business rules, atomic multi-field updates and reference verification."

    def __init__(self, settings: dict[str, Any]) -> None:
        if not isinstance(settings, dict) or not isinstance(settings.get("initial_state"), dict):
            raise EnvironmentError("Reality template requires initial_state object")
        if not isinstance(settings.get("actions"), dict) or not settings["actions"]:
            raise EnvironmentError("Reality template requires action definitions")
        if len(settings["actions"]) > 64 or _size(settings["initial_state"]) > MAX_STATE_BYTES:
            raise EnvironmentError("Reality template exceeds action/state limits")
        if settings.get("approved") is not True:
            raise EnvironmentError("Reality rules require explicit approved=true")
        self.settings = copy.deepcopy(settings)
        self.name = str(settings.get("name", self.name))
        self.description = str(settings.get("description", self.description))
        self.instruction = str(settings.get("instruction", "Complete the simulated workflow."))
        self.tasks = (str(settings.get("task", "default")),)
        self._actions: list[ActionSpec] = []
        for name, spec in settings["actions"].items():
            if not isinstance(name, str) or not ACTION_RE.fullmatch(name):
                raise EnvironmentError("Invalid reality action name")
            if not isinstance(spec, dict) or not isinstance(spec.get("effects"), list):
                raise EnvironmentError("Actions need an effects list")
            if len(spec["effects"]) > 16 or len(spec["effects"]) == 0:
                raise EnvironmentError("An action needs 1..16 effects")
            parameters = spec.get("parameters", {})
            if not isinstance(parameters, dict) or len(parameters) > 16:
                raise EnvironmentError("Invalid action parameters")
            for rule in spec.get("guards", []):
                if not isinstance(rule, dict) or rule.get("operator", "eq") not in (
                        "eq", "ne", "exists", "contains", "gte", "gt", "lte", "lt"):
                    raise EnvironmentError("Invalid business guard")
            for effect in spec["effects"]:
                if not isinstance(effect, dict) or effect.get("operation") not in (
                        "set", "append", "increment"):
                    raise EnvironmentError("Invalid state effect")
                if "from_param" in effect and effect["from_param"] not in parameters:
                    raise EnvironmentError("Unknown effect parameter")
            self._actions.append(ActionSpec(
                name, str(spec.get("description", name)), parameters, tuple(parameters)
            ))

    def initial_state(self, seed: int) -> dict[str, Any]:
        state = copy.deepcopy(self.settings["initial_state"])
        variants = self.settings.get("variants", [])
        if variants:
            if not isinstance(variants, list) or len(variants) > 100:
                raise EnvironmentError("Invalid reality variants")
            from random import Random
            state = overlay(state, Random(seed).choice(variants))
        return state

    def actions(self) -> tuple[ActionSpec, ...]:
        return tuple(self._actions)

    def perform(self, state: dict[str, Any], action: str,
                params: dict[str, Any]) -> dict[str, Any]:
        spec = self.settings["actions"].get(action)
        if spec is None:
            raise EnvironmentError(f"Unknown reality action: {action}")
        required = spec.get("parameters", {})
        if set(params) != set(required):
            raise EnvironmentError("Missing or unexpected action parameters")
        for key, schema in required.items():
            if not isinstance(schema, dict):
                raise EnvironmentError("Invalid parameter schema")
            value = params[key]
            kind = schema.get("type")
            valid = (
                kind == "string" and isinstance(value, str) or
                kind == "boolean" and isinstance(value, bool) or
                kind == "number" and isinstance(value, (int, float))
                and not isinstance(value, bool) or
                kind == "object" and isinstance(value, dict)
            )
            if not valid or "enum" in schema and value not in schema["enum"]:
                raise EnvironmentError(f"Invalid parameter: {key}")
        draft = copy.deepcopy(state)
        for guard in spec.get("guards", []):
            path = guard.get("path", "")
            try:
                parent, key = at(draft, path, params)
                value = parent[key]
                exists = True
            except EnvironmentError:
                value, exists = None, False
            operator = guard.get("operator", "eq")
            expected = guard.get("value")
            if "from_param" in guard:
                expected = params[guard["from_param"]]
            if operator == "exists":
                passed = exists
            elif operator == "eq":
                passed = exists and type(value) is type(expected) and value == expected
            elif operator == "ne":
                passed = exists and value != expected
            elif operator == "contains":
                passed = exists and isinstance(value, (str, list, dict)) and expected in value
            elif operator in ("gt", "gte", "lt", "lte", "lt"):
                passed = (exists and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                         for v in (value, expected)) and {
                    "gt": lambda: value > expected, "gte": lambda: value >= expected,
                    "lt": lambda: value < expected, "lte": lambda: value <= expected,
                }[operator]())
            else:
                raise EnvironmentError("Unknown guard operator")
            if not passed:
                raise EnvironmentError("Business rule denied action")
        results = []
        for effect in spec["effects"]:
            value = params[effect["from_param"]] if "from_param" in effect else effect.get("value")
            result = transition(draft, effect["operation"], effect.get("path", ""), value, params)
            results.append({"path": effect["path"], "result": result})
        if _size(draft) > MAX_STATE_BYTES:
            raise EnvironmentError("State exceeds 64 KiB")
        state.clear()
        state.update(draft)
        return {"effects": results}

    def validate(self, state: dict[str, Any]) -> ValidationResult:
        checks = self.settings.get("checks")
        if checks is None:
            checks = [{"name": "state_exists", "path": next(iter(state)), "operator": "exists"}]
        return score_checks(state, checks)


def verify_reference_cases(settings: dict[str, Any],
                           cases: Sequence[ReferenceCase]) -> dict[str, Any]:
    """Compare actual state changes, without ever executing against real systems."""
    simulator = RealityEnvironment(settings)
    results = []
    for case in cases:
        state = copy.deepcopy(case.before)
        try:
            response = simulator.perform(state, case.action, copy.deepcopy(case.parameters))
            diffs = _differences(case.after, state)
            if case.response is not None:
                diffs += _differences(case.response, response, "$response")
        except EnvironmentError as exc:
            diffs = [{"path": "$error", "expected": "successful execution",
                      "actual": str(exc)}]
        results.append({"case_id": case.case_id, "action": case.action,
                        "passed": not diffs, "differences": diffs})
    total = len(results)
    return {"tested": total, "passed": sum(item["passed"] for item in results),
            "pass_rate": sum(item["passed"] for item in results) / total if total else 0.0,
            "results": results, "scope": "recorded reference cases only"}


def inspect_openapi(document: dict[str, Any]) -> list[dict[str, str]]:
    """Inventory APIs without falsely inventing their data mutations."""
    if not isinstance(document, dict) or not isinstance(document.get("paths"), dict):
        raise ValueError("Expected an OpenAPI document with paths")
    items = []
    for path, operations in document["paths"].items():
        if not isinstance(path, str) or not path.startswith("/") or not isinstance(operations, dict):
            raise ValueError("Invalid OpenAPI path")
        for method, spec in operations.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            if not isinstance(spec, dict):
                raise ValueError("Invalid OpenAPI operation")
            items.append({"method": method.upper(), "path": path,
                          "operation_id": str(spec.get("operationId", "")),
                          "status": "interface_only_no_behavior_inferred"})
    return items


def cases_to_scenarios(cases: Sequence[ReferenceCase]) -> list[dict[str, Any]]:
    """Generate held-out, reference-derived deterministic scenario candidates."""
    scenarios = []
    for case in cases:
        changes = _changed_leaves(case.before, case.after)
        checks = [
            {"name": f"{case.action}_{index}", "path": path,
             "operator": "eq", "equals": value}
            for index, (path, value) in enumerate(changes.items())
        ]
        if checks:
            scenarios.append({"name": case.case_id or case.action,
                              "state_overrides": copy.deepcopy(case.before),
                              "checks": checks,
                              "reference_source": case.source})
    return scenarios
