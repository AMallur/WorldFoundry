"""Optional trusted usage forwarding to a Stripe Billing Meter.

Only operator-verified worker usage is eligible. Configure a Stripe meter
that accepts the default customer identifier and value payload keys.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from backend.core.config import Settings
from backend.core.supabase import SupabaseStore


def report_meter_usage(store: SupabaseStore, settings: Settings) -> int:
    meter_name = os.getenv("STRIPE_METER_EVENT_NAME")
    if not settings.stripe_secret_key or not meter_name:
        raise RuntimeError("Stripe metered billing is not configured")
    pending = store.select("wf_managed_usage",
                           filters={"stripe_reported_at": "is.null"},
                           limit=100)
    count = 0
    for row in pending:
        subscriptions = store.select("wf_billing_customers", filters={
            "project_id": "eq." + row["project_id"], "plan": "eq.pro",
            "subscription_status": "eq.active",
        }, limit=1)
        if not subscriptions:
            continue
        customer_id = subscriptions[0]["stripe_customer_id"]
        params = {
            "event_name": meter_name,
            "identifier": "worldfoundry-" + row["managed_run_id"],
            "payload[stripe_customer_id]": customer_id,
            "payload[value]": str(row["episodes"]),
        }
        payload = urlencode(params).encode()
        request = Request(
            "https://api.stripe.com/v1/billing/meter_events",
            data=payload, method="POST",
            headers={"Authorization": "Bearer " + settings.stripe_secret_key,
                     "Content-Type": "application/x-www-form-urlencoded"},
        )
        with urlopen(request, timeout=20) as response:
            if response.status != 200:
                raise RuntimeError("Stripe meter reporting failed")
            json.load(response)
        store.update("wf_managed_usage", {
            "stripe_reported_at": datetime.now(UTC).isoformat(),
        }, {"managed_run_id": "eq." + row["managed_run_id"],
            "stripe_reported_at": "is.null"})
        count += 1
    return count
