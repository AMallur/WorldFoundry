"""One-pass outbox dispatcher; invoke periodically through a private Cloud Run Job.

Admission happens inside the WorldFoundry customer API. This process only
enqueues previously admitted cloud_tasks jobs. No customer code executes here.
"""
from __future__ import annotations

import os

from backend.core.config import Settings
from backend.core.supabase import SupabaseStore
from backend.orchestration.cloud_tasks import TaskConfig, enqueue_run


def dispatch_pending(store: SupabaseStore, tasks: TaskConfig, *, limit: int = 20) -> int:
    pending = store.select("wf_managed_runs", filters={
        "status": "eq.queued", "executor": "eq.cloud_tasks",
        "queued_to_cloud_at": "is.null",
    }, columns="id", order="created_at.asc", limit=limit)
    sent = 0
    for run in pending:
        enqueue_run(run["id"], tasks)
        # Task ID is deterministic so duplicate dispatches cannot create new work.
        store.update("wf_managed_runs", {
            "queued_to_cloud_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc).isoformat(),
        }, {"id": "eq." + run["id"], "queued_to_cloud_at": "is.null",
            "status": "eq.queued"})
        sent += 1
    return sent


def main() -> None:
    settings = Settings.from_env()
    names = ("GCP_PROJECT_ID", "GCP_REGION", "GCP_TASK_QUEUE",
             "WF_CLOUD_WORKER_URL", "GCP_TASK_SERVICE_ACCOUNT")
    if any(not os.getenv(name) for name in names):
        raise RuntimeError("GCP task dispatcher settings not configured")
    task_settings = TaskConfig(
        project_id=os.environ["GCP_PROJECT_ID"], region=os.environ["GCP_REGION"],
        queue=os.environ["GCP_TASK_QUEUE"],
        worker_url=os.environ["WF_CLOUD_WORKER_URL"],
        service_account_email=os.environ["GCP_TASK_SERVICE_ACCOUNT"],
        worker_shared_token=settings.worker_shared_token,
    )
    store = SupabaseStore(settings.supabase_url, settings.supabase_service_key)
    print("Dispatched", dispatch_pending(store, task_settings), "WorldFoundry jobs")


if __name__ == "__main__":
    main()
