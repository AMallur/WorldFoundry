"""Cloud Run worker; only trusted internal tasks can call this module."""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from backend.core.supabase import StorageError, SupabaseStore
from runtime.scripted import ScenarioError, run_plan


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def one(store: SupabaseStore, table: str, **filters: str) -> dict[str, Any]:
    rows = store.select(table, filters={key: "eq." + str(val) for key, val in filters.items()},
                        limit=1)
    if not rows:
        raise StorageError("Missing run or resource")
    return rows[0]


def execute_run(store: SupabaseStore, run_id: str) -> dict[str, Any]:
    """Claim exactly once, verify every resource belongs to the run's project."""
    UUID(run_id)
    job = one(store, "wf_managed_runs", id=run_id)
    if job["executor"] != "cloud_tasks":
        raise ValueError("Worker accepts cloud_tasks jobs only")
    if job["status"] != "queued":
        return {"status": job["status"], "run_id": run_id, "duplicate": True}
    claimed = store.update("wf_managed_runs", {
        "status": "running", "claimed_at": timestamp(),
        "updated_at": timestamp(), "attempt_count": job["attempt_count"] + 1,
    }, {"id": "eq." + run_id, "status": "eq.queued", "executor": "eq.cloud_tasks"})
    if not claimed:
        return {"status": "running", "run_id": run_id, "duplicate": True}

    project_id = job["project_id"]
    try:
        expected_kinds = {
            "environment_id": "environment", "scenario_id": "scenario", "agent_id": "agent",
        }
        resources = {}
        for key, expected in expected_kinds.items():
            resource = one(store, "wf_resources", id=job[key], project_id=project_id)
            if resource["kind"] != expected:
                raise ScenarioError("Resource kind mismatch")
            resources[key] = resource["config"]
        env = resources["environment_id"]
        scenario = resources["scenario_id"]
        plan = resources["agent_id"].get("plan", [])
        scores = []
        elapsed_total = 0
        action_total = 0
        for ordinal in range(job["requested_episodes"]):
            start = time.monotonic_ns()
            result = run_plan(env, scenario, plan, seed=job["seed"] + ordinal,
                              max_steps=job["max_steps"])
            trace = ("\n".join(json.dumps(event, separators=(",", ":"))
                               for event in result.events) + "\n").encode()
            if len(trace) > 5_000_000:
                raise StorageError("Trace too large")
            key = project_id + "/managed/" + run_id + "/" + str(ordinal) + ".jsonl"
            store.upload("wf-artifacts", key, trace, "application/x-ndjson")
            ms = max(0, (time.monotonic_ns() - start) // 1_000_000)
            store.insert("wf_managed_episodes", {
                "project_id": project_id, "managed_run_id": run_id,
                "ordinal": ordinal, "seed": job["seed"] + ordinal,
                "status": "passed" if result.passed else "failed",
                "score": result.score, "checks": result.checks,
                "action_count": result.actions, "duration_ms": ms,
                "trace_object_key": key,
            })
            store.insert("wf_artifacts", {
                "project_id": project_id, "managed_run_id": run_id,
                "kind": "trace", "name": "episode-" + str(ordinal) + ".jsonl",
                "storage_key": key, "bytes": len(trace),
                "content_type": "application/x-ndjson",
            })
            scores.append(result.score)
            elapsed_total += ms
            action_total += result.actions
        store.insert("wf_managed_usage", {
            "project_id": project_id, "managed_run_id": run_id,
            "episodes": len(scores), "actions": action_total,
            "elapsed_ms": elapsed_total, "source": "cloud_verified",
        })
        completed = store.update("wf_managed_runs", {
            "status": "completed", "score_mean": sum(scores) / len(scores),
            "completed_episodes": len(scores), "finished_at": timestamp(),
            "updated_at": timestamp(),
        }, {"id": "eq." + run_id, "status": "eq.running"})
        if not completed:
            raise StorageError("Could not complete run")
        return completed[0]
    except Exception:
        store.update("wf_managed_runs", {
            "status": "failed", "error_code": "execution_failed",
            "finished_at": timestamp(), "updated_at": timestamp(),
        }, {"id": "eq." + run_id, "status": "eq.running"})
        raise
