"""Dispatch WorldFoundry managed runs to a private Cloud Run service via OIDC."""
from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class TaskConfig:
    project_id: str
    region: str
    queue: str
    worker_url: str
    service_account_email: str
    worker_shared_token: str


def enqueue_run(run_id: str, config: TaskConfig, client=None) -> str:
    """Idempotent task name; Cloud Tasks de-duplicates repeated dispatch attempts."""
    import uuid

    from google.api_core.exceptions import AlreadyExists
    from google.cloud import tasks_v2

    uuid.UUID(run_id)
    if not config.worker_url.startswith("https://"):
        raise ValueError("Cloud Run worker must use HTTPS")
    if client is None:
        client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(config.project_id, config.region, config.queue)
    name = client.task_path(config.project_id, config.region,
                            config.queue, "wf-" + run_id.replace("-", ""))
    task = {
        "name": name,
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": config.worker_url.rstrip("/") + "/tasks/execute",
            "headers": {
                "Content-Type": "application/json",
                "X-WF-Worker-Token": config.worker_shared_token,
            },
            "body": json.dumps({"run_id": run_id}).encode("utf-8"),
            "oidc_token": {
                "service_account_email": config.service_account_email,
                "audience": config.worker_url.rstrip("/"),
            },
        },
    }
    try:
        client.create_task(request={"parent": parent, "task": task})
    except AlreadyExists:
        pass
    return name
