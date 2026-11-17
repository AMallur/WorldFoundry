"""Bounded declarative simulator; never executes untrusted Python or HTTP calls."""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from typing import Any

SEGMENT = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")
BLOCKED = {"__proto__", "prototype", "constructor"}
MAX_STATE_BYTES = 65536


class ScenarioError(ValueError):
    pass


def safe_path(path: str, params: dict[str, Any]) -> list[str]:
    if not isinstance(path, str) or not path or len(path) > 256:
        raise ScenarioError("Invalid state path")
    result = []
    for part in path.split("."):
        name = params.get(part[1:]) if part.startswith("$") else part
        if not isinstance(name, str) or not SEGMENT.fullmatch(name) or name in BLOCKED:
            raise ScenarioError("Unsafe state path")
        result.append(name)
    return result


def target(state: dict[str, Any], path: str, params: dict[str, Any]):
    parts = safe_path(path, params)
    cursor: Any = state
    for part in parts[:-1]:
        if not isinstance(cursor, dict) or part not in cursor:
            raise ScenarioError("Unknown state path")
        cursor = cursor[part]
    if not isinstance(cursor, dict) or parts[-1] not in cursor:
        raise ScenarioError("Unknown state path")
    return cursor, parts[-1]


def apply(state: dict[str, Any], op: str, path: str, value: Any,
          params: dict[str, Any]) -> Any:
    parent, key = target(state, path, params)
    if op == "read":
        return copy.deepcopy(parent[key])
    if op == "set":
        parent[key] = copy.deepcopy(value)
    elif op == "append":
        if not isinstance(parent[key], list) or len(parent[key]) >= 1000:
            raise ScenarioError("Not an appendable array")
        parent[key].append(copy.deepcopy(value))
    elif op == "increment":
        if not isinstance(parent[key], (int, float)) or isinstance(parent[key], bool) or (
            not isinstance(value, (int, float)) or isinstance(value, bool)
        ):
            raise ScenarioError("Invalid numeric increment")
        parent[key] += value
    else:
        raise ScenarioError("Unsupported action operation")
    if len(json.dumps(state, separators=(",", ":")).encode()) > MAX_STATE_BYTES:
        raise ScenarioError("State size limit exceeded")
    return copy.deepcopy(parent[key])


def validate_definitions(env: dict[str, Any], scenario: dict[str, Any],
                         plan: list[dict[str, Any]], max_steps: int) -> None:
    if not isinstance(env, dict) or not isinstance(env.get("initial_state"), dict):
        raise ScenarioError("Invalid environment")
    if len(json.dumps(env["initial_state"]).encode()) > MAX_STATE_BYTES:
        raise ScenarioError("Initial state too large")
    actions = env.get("actions")
    if not isinstance(actions, dict) or not 1 <= len(actions) <= 64:
        raise ScenarioError("Invalid environment actions")
    for name, action in actions.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name):
            raise ScenarioError("Invalid action name")
        if not isinstance(action, dict) or action.get("operation") not in (
            "read", "set", "append", "increment"
        ):
            raise ScenarioError("Unsupported action definition")
        safe_path(action.get("path", ""), {part[1:]: "example" for part in str(
            action.get("path", "")).split(".") if part.startswith("$")})
    if not isinstance(scenario, dict) or not isinstance(scenario.get("checks"), list):
        raise ScenarioError("Invalid scenario")
    if not 1 <= len(scenario["checks"]) <= 64 or len(scenario.get("events", [])) > 64:
        raise ScenarioError("Scenario limit exceeded")
    for check in scenario["checks"]:
        if not isinstance(check, dict) or not isinstance(check.get("name"), str):
            raise ScenarioError("Invalid validation check")
        safe_path(check.get("path", ""), {})
    for event in scenario.get("events", []):
        if not isinstance(event, dict) or not 1 <= event.get("at_step", 0) <= 1000:
            raise ScenarioError("Invalid scenario event")
        if event.get("operation") not in ("set", "append", "increment"):
            raise ScenarioError("Invalid scenario event operation")
        safe_path(event.get("path", ""), {})
    if not isinstance(plan, list) or not 1 <= len(plan) <= max_steps:
        raise ScenarioError("Invalid agent plan")
    for step in plan:
        if not isinstance(step, dict) or step.get("action") not in actions:
            raise ScenarioError("Unknown agent action")
        if not isinstance(step.get("parameters", {}), dict):
            raise ScenarioError("Invalid action parameters")


@dataclass
class EpisodeResult:
    passed: bool
    score: float
    checks: list[dict[str, Any]]
    events: list[dict[str, Any]]
    actions: int


def run_plan(env: dict[str, Any], scenario: dict[str, Any],
             plan: list[dict[str, Any]], *, seed: int = 0,
             max_steps: int = 30) -> EpisodeResult:
    validate_definitions(env, scenario, plan, max_steps)
    state = copy.deepcopy(env["initial_state"])
    trace: list[dict[str, Any]] = [{"type": "episode.started", "seed": seed}]
    actions = env["actions"]
    for index, step in enumerate(plan, start=1):
        action = actions[step["action"]]
        params = step.get("parameters", {})
        specs = action.get("parameters", {})
        if set(params) != set(specs):
            raise ScenarioError("Missing or unexpected action parameters")
        for name, spec in specs.items():
            value = params[name]
            allowed_type = spec.get("type")
            valid = {
                "string": isinstance(value, str),
                "number": isinstance(value, (float, int)) and not isinstance(value, bool),
                "boolean": isinstance(value, bool),
                "object": isinstance(value, dict),
            }.get(allowed_type, False)
            if not valid or "enum" in spec and value not in spec["enum"]:
                raise ScenarioError("Invalid action parameter value")
        value = params[action["from_param"]] if action.get("from_param") else action.get("value")
        observation = apply(state, action["operation"], action["path"], value, params)
        trace.append({"type": "agent.action", "step": index, "action": step["action"],
                      "parameters": params, "observation": observation})
        for event in scenario.get("events", []):
            if event["at_step"] == index:
                change = apply(state, event["operation"], event["path"], event["value"], {})
                trace.append({"type": "scenario.event", "step": index, "path": event["path"],
                              "result": change})
    checks = []
    for check in scenario["checks"]:
        try:
            container, key = target(state, check["path"], {})
            matched = container[key] == check["equals"]
        except ScenarioError:
            matched = False
        checks.append({"name": check["name"], "passed": matched})
    score = sum(check["passed"] for check in checks) / len(checks)
    passed = all(check["passed"] for check in checks)
    trace.append({"type": "episode.finished", "passed": passed, "score": score, "checks": checks})
    return EpisodeResult(passed, score, checks, trace, len(plan))
