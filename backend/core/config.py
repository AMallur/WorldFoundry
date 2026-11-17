"""Required backend secrets stay on Cloud Run, never in the PyPI package."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_service_key: str
    worker_shared_token: str
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id: str = ""
    checkout_success_url: str = ""
    checkout_cancel_url: str = ""

    @classmethod
    def from_env(cls) -> Settings:
        required = ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "WF_WORKER_SHARED_TOKEN")
        missing = [key for key in required if not os.getenv(key)]
        if missing:
            raise RuntimeError("Missing backend secret configuration: " + ", ".join(missing))
        return cls(
            supabase_url=os.environ["SUPABASE_URL"],
            supabase_service_key=os.environ["SUPABASE_SERVICE_ROLE_KEY"],
            worker_shared_token=os.environ["WF_WORKER_SHARED_TOKEN"],
            stripe_secret_key=os.getenv("STRIPE_SECRET_KEY", ""),
            stripe_webhook_secret=os.getenv("STRIPE_WEBHOOK_SECRET", ""),
            stripe_price_id=os.getenv("STRIPE_PRICE_ID", ""),
            checkout_success_url=os.getenv("WF_CHECKOUT_SUCCESS_URL", ""),
            checkout_cancel_url=os.getenv("WF_CHECKOUT_CANCEL_URL", ""),
        )
