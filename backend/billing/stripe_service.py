"""Stripe Checkout and signed webhook processing, server-only credentials."""
from __future__ import annotations

from typing import Any

from backend.core.config import Settings
from backend.core.supabase import SupabaseStore


def create_checkout(store: SupabaseStore, settings: Settings,
                    project_id: str, owner_id: str) -> str:
    if not (settings.stripe_secret_key and settings.stripe_price_id
            and settings.checkout_success_url and settings.checkout_cancel_url):
        raise RuntimeError("Stripe Checkout not configured")
    import stripe

    if not store.select("wf_projects",
                        filters={"id": "eq." + project_id, "owner_id": "eq." + owner_id},
                        limit=1):
        raise PermissionError("Unknown WorldFoundry project")
    stripe.api_key = settings.stripe_secret_key
    bindings = store.select("wf_billing_customers",
                            filters={"project_id": "eq." + project_id}, limit=1)
    customer_id = bindings[0]["stripe_customer_id"] if bindings else None
    if not customer_id:
        customer = stripe.Customer.create(metadata={"wf_project_id": project_id})
        customer_id = customer.id
        if bindings:
            store.update("wf_billing_customers", {
                "stripe_customer_id": customer_id,
            }, {"project_id": "eq." + project_id})
        else:
            store.insert("wf_billing_customers", {
                "project_id": project_id, "stripe_customer_id": customer_id,
            })
    session = stripe.checkout.Session.create(
        customer=customer_id, mode="subscription",
        line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
        success_url=settings.checkout_success_url,
        cancel_url=settings.checkout_cancel_url,
        client_reference_id=project_id,
        metadata={"wf_project_id": project_id},
    )
    return session.url


def process_webhook(store: SupabaseStore, settings: Settings,
                    raw_body: bytes, signature: str) -> dict[str, Any]:
    if not settings.stripe_webhook_secret:
        raise RuntimeError("Stripe webhook not configured")
    import stripe

    event = stripe.Webhook.construct_event(raw_body, signature, settings.stripe_webhook_secret)
    event_id = event["id"]
    if store.select("wf_billing_events", filters={"event_id": "eq." + event_id}, limit=1):
        return {"received": True, "duplicate": True}

    kind = event["type"]
    payload = event["data"]["object"]
    if kind in ("customer.subscription.created", "customer.subscription.updated",
                "customer.subscription.deleted"):
        customer_id = payload.get("customer")
        bindings = store.select("wf_billing_customers",
                                filters={"stripe_customer_id": "eq." + customer_id}, limit=1)
        if bindings:
            status = "canceled" if kind == "customer.subscription.deleted" else payload["status"]
            active = status in ("active", "trialing")
            store.update("wf_billing_customers", {
                "stripe_subscription_id": payload.get("id"),
                "subscription_status": status,
                "plan": "pro" if active else "free",
                "monthly_episode_limit": 1000 if active else 20,
            }, {"project_id": "eq." + bindings[0]["project_id"]})
    elif kind == "invoice.payment_failed":
        customer_id = payload.get("customer")
        bindings = store.select("wf_billing_customers",
                                filters={"stripe_customer_id": "eq." + customer_id}, limit=1)
        if bindings:
            store.update("wf_billing_customers", {
                "subscription_status": "past_due", "plan": "free",
                "monthly_episode_limit": 20,
            }, {"project_id": "eq." + bindings[0]["project_id"]})

    # Record event only once all writes succeed; retries may safely repeat
    # idempotent subscription-status updates.
    store.insert("wf_billing_events", {"event_id": event_id, "event_type": kind})
    return {"received": True, "duplicate": False}
