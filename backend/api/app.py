"""Private Cloud Run worker API. Cloud Run IAM must reject unauthenticated traffic."""
from __future__ import annotations

import hmac
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request

from backend.core.config import Settings
from backend.core.supabase import SupabaseStore
from backend.workers.execute import execute_run

app = FastAPI(title="WorldFoundry private worker", docs_url=None, redoc_url=None)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/tasks/execute")
async def execute_task(request: Request,
                       x_wf_worker_token: str | None = Header(default=None)):
    try:
        config = Settings.from_env()
        store = SupabaseStore(config.supabase_url, config.supabase_service_key)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Service not configured") from exc
    if not x_wf_worker_token or not hmac.compare_digest(
        x_wf_worker_token, config.worker_shared_token
    ):
        raise HTTPException(status_code=403, detail="Forbidden")
    # Cloud Run IAM MUST also enforce task service-account authentication.
    try:
        payload = await request.json()
        run_id = str(UUID(payload["run_id"]))
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid task payload") from exc
    return execute_run(store, run_id)
