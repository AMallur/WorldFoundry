"""Public billing webhook service; every write requires Stripe signature or internal token."""
from __future__ import annotations

import hmac
import os
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request

from backend.billing.stripe_service import create_checkout, process_webhook
from backend.core.config import Settings
from backend.core.supabase import SupabaseStore

app = FastAPI(title="WorldFoundry Billing", docs_url=None, redoc_url=None)


def backend() -> tuple[Settings, SupabaseStore]:
    try:
        config = Settings.from_env(require_worker_token=False)
        return config, SupabaseStore(config.supabase_url, config.supabase_service_key)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Service not configured") from exc


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/billing/checkout")
async def checkout(request: Request,
                   x_wf_internal_token: str | None = Header(default=None)):
    config, store = backend()
    token = os.getenv("WF_BILLING_SHARED_TOKEN", "")
    if not x_wf_internal_token or not token or not hmac.compare_digest(
        x_wf_internal_token, token
    ):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        body = await request.json()
        project_id = str(UUID(body["project_id"]))
        owner_id = str(UUID(body["owner_id"]))
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid project") from exc
    try:
        return {"url": create_checkout(store, config, project_id, owner_id)}
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail="Unknown project") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Billing unavailable") from exc


@app.post("/billing/stripe/webhook")
async def webhook(request: Request, stripe_signature: str | None = Header(default=None)):
    config, store = backend()
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Missing signature")
    try:
        return process_webhook(store, config, await request.body(), stripe_signature)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Billing unavailable") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Webhook rejected") from exc
