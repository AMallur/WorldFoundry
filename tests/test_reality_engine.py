"""Reality engine: executable rules, evidence handling and agent connections."""
from __future__ import annotations

import copy
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from worldfoundry import (
    RealityEnvironment,
    ReferenceCase,
    WorldFoundry,
    cases_to_scenarios,
    inspect_openapi,
    propose_actions,
    verify_reference_cases,
)
from worldfoundry.environments import EnvironmentError
from worldfoundry.integrations.meta_are import MetaARERunner


def config():
    return {
        "name": "Access approvals",
        "approved": True,
        "task": "approve",
        "instruction": "Approve request R1 if permitted.",
        "initial_state": {"tickets": {
            "R1": {"status": "pending", "approved": False},
            "R2": {"status": "closed", "approved": False},
        }},
        "actions": {
            "approve": {
                "parameters": {"request_id": {"type": "string"}},
                "guards": [{"path": "tickets.$request_id.status", "operator": "eq",
                            "value": "pending"}],
                "effects": [
                    {"operation": "set", "path": "tickets.$request_id.status",
                     "value": "approved"},
                    {"operation": "set", "path": "tickets.$request_id.approved",
                     "value": True},
                ],
            }
        },
        "checks": [
            {"name": "approved", "path": "tickets.R1.status", "equals": "approved"},
            {"name": "audit", "path": "tickets.R1.approved", "equals": True},
        ],
    }


def test_reality_environment_runs_in_existing_sdk(tmp_path):
    wf = WorldFoundry.local(tmp_path)
    environment = wf.environments.create(template="reality", config=config())
    episode = wf.start(environment.id)
    response = wf.act(episode.id, "approve", request_id="R1").observation
    assert len(response["effects"]) == 2
    assert wf.get(episode.id).state["tickets"]["R1"]["approved"] is True
    with pytest.raises(EnvironmentError, match="denied"):
        wf.act(episode.id, "approve", request_id="R1")
    assert wf.get(episode.id).state["tickets"]["R1"]["status"] == "approved"
    assert wf.submit(episode.id).score == 1.0
    assert any(x["type"] == "action.failed" for x in wf.get(episode.id).trace)


def test_guards_fail_before_any_state_mutates():
    environment = RealityEnvironment(config())
    source = environment.initial_state(0)
    prior = copy.deepcopy(source)
    with pytest.raises(EnvironmentError, match="denied"):
        environment.perform(source, "approve", {"request_id": "R2"})
    assert source == prior


def test_effects_roll_back_on_partial_failure():
    settings = config()
    settings["actions"]["approve"]["effects"].append({
        "operation": "set", "path": "tickets.R1.nonexistent", "value": 5
    })
    environment = RealityEnvironment(settings)
    state = environment.initial_state(0)
    prior = copy.deepcopy(state)
    with pytest.raises(EnvironmentError):
        environment.perform(state, "approve", {"request_id": "R1"})
    assert state == prior


def test_permission_to_activate_rules_is_explicit(tmp_path):
    settings = config()
    settings["approved"] = False
    wf = WorldFoundry.local(tmp_path)
    with pytest.raises(EnvironmentError, match="approved"):
        wf.environments.create(template="reality", config=settings)


def test_differential_verification_uses_observed_state():
    settings = config()
    before = copy.deepcopy(settings["initial_state"])
    after = copy.deepcopy(before)
    after["tickets"]["R1"] = {"status": "approved", "approved": True}
    reference = ReferenceCase(
        action="approve", parameters={"request_id": "R1"},
        before=before, after=after, case_id="reference-1"
    )
    result = verify_reference_cases(settings, [reference])
    assert result["tested"] == 1
    assert result["passed"] == 1
    assert result["pass_rate"] == 1.0

    after["tickets"]["R1"]["status"] = "rejected"
    mismatch = ReferenceCase(action="approve", parameters={"request_id": "R1"},
                             before=before, after=after, case_id="different")
    report = verify_reference_cases(settings, [mismatch])
    assert report["passed"] == 0
    assert report["results"][0]["differences"][0]["path"] == "$.tickets.R1.status"


def test_proposals_are_draft_not_automatically_approved():
    observations = [
        ReferenceCase("change", {"order": {"status": "open"}},
                      {"order": {"status": "closed"}}, {"value": "closed"}),
        ReferenceCase("change", {"order": {"status": "pending"}},
                      {"order": {"status": "resolved"}}, {"value": "resolved"}),
    ]
    proposal = propose_actions(observations)
    assert proposal["status"] == "draft_requires_verification"
    assert proposal["actions"]["change"]["effects"] == [
        {"operation": "set", "path": "order.status", "from_param": "value"}
    ]
    scenarios = cases_to_scenarios(observations)
    assert len(scenarios) == 2
    assert scenarios[0]["checks"][0]["path"] == "order.status"


def test_unsafe_or_unverified_evidence_does_not_pass_silently():
    with pytest.raises(ValueError, match="credential"):
        ReferenceCase("approve", {"api_key": "do-not-store"}, {})
    with pytest.raises(ValueError, match="Schema changed"):
        propose_actions([
            ReferenceCase("create", {"x": {}}, {"x": {"new": "a"}}),
            ReferenceCase("create", {"x": {}}, {"x": {"new": "b"}}),
        ])


def test_openapi_import_is_inventory_only():
    spec = {"openapi": "3.1.0", "paths": {
        "/tickets/{id}": {
            "get": {"operationId": "readTicket"},
            "patch": {"operationId": "updateTicket"},
            "parameters": [],
        }
    }}
    inventory = inspect_openapi(spec)
    assert [x["method"] for x in inventory] == ["GET", "PATCH"]
    assert all(x["status"] == "interface_only_no_behavior_inferred" for x in inventory)


def test_meta_are_runner_executes_only_validated_local_command():
    runner = MetaARERunner(timeout_seconds=30)
    with patch("shutil.which", return_value="/usr/bin/are-run"), \
         patch("subprocess.run", return_value=CompletedProcess([], 0, "passed", "")) as call:
        result = runner.run("scenario_find_image_file")
    assert result.exit_code == 0
    assert "passed" in result.stdout
    assert call.call_args.kwargs["shell"] is False
    with pytest.raises(ValueError, match="Unsafe"):
        runner.run("../bad scenario")
