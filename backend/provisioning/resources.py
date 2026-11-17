"""Provision a default free-tier entitlement in the central WorldFoundry database."""
from __future__ import annotations

from backend.core.supabase import SupabaseStore


def provision_project(store: SupabaseStore, project_id: str) -> dict:
    existing = store.select("wf_billing_customers",
                            filters={"project_id": "eq." + project_id}, limit=1)
    if existing:
        return existing[0]
    return store.insert("wf_billing_customers", {
        "project_id": project_id, "plan": "free",
        "subscription_status": "inactive", "monthly_episode_limit": 20,
    })
