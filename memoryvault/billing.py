"""Billing & usage metering (#14) — paste a Stripe key, billing works.

Pricing model (the plan from docs/BUSINESS.md):
  - Rescue: one-time (invoiced per project, tracked as a usage event)
  - Platform subscription: base fee + per-connected-system/month

Usage is metered locally (every rescue, every connected system, every
memory synced) and reported to Stripe as metered usage. Without a Stripe
key, metering still runs locally so you can see usage — it just doesn't
bill. The webhook endpoint is wired in the API.
"""
from __future__ import annotations

import json
import os
import time
from typing import Optional

from .config import CONFIG


class Meter:
    """Local usage ledger — always on, per org. Source of truth for billing."""

    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, "usage.jsonl")
        os.makedirs(data_dir, exist_ok=True)

    def record(self, org: str, event: str, qty: int = 1, meta: dict = None):
        rec = {"ts": time.time(), "org": org, "event": event, "qty": qty,
               "meta": meta or {}}
        with open(self.path, "a") as f:
            f.write(json.dumps(rec) + "\n")

    def summary(self, org: str) -> dict:
        totals = {}
        if os.path.exists(self.path):
            with open(self.path) as f:
                for line in f:
                    r = json.loads(line)
                    if r["org"] == org:
                        totals[r["event"]] = totals.get(r["event"], 0) + r["qty"]
        connectors = totals.get("connector_active", 0)
        rescues = totals.get("rescue", 0)
        est = connectors * 500 + rescues * 15000  # $/mo connectors + $/rescue
        return {"org": org, "events": totals,
                "estimated_usd": est,
                "plan": "active" if CONFIG.stripe_secret_key else "demo"}


class StripeBilling:
    """Thin Stripe wrapper. Activates only when STRIPE_SECRET_KEY is set."""

    def __init__(self):
        self.enabled = bool(CONFIG.stripe_secret_key)
        self._stripe = None
        if self.enabled:
            try:
                import stripe
                stripe.api_key = CONFIG.stripe_secret_key
                self._stripe = stripe
            except Exception:
                self.enabled = False

    def create_customer(self, org: str, email: str) -> Optional[str]:
        if not self.enabled:
            return None
        c = self._stripe.Customer.create(email=email, metadata={"org": org})
        return c["id"]

    def start_subscription(self, customer_id: str) -> Optional[str]:
        if not self.enabled or not CONFIG.stripe_price_platform:
            return None
        items = [{"price": CONFIG.stripe_price_platform}]
        if CONFIG.stripe_price_per_connector:
            items.append({"price": CONFIG.stripe_price_per_connector})
        sub = self._stripe.Subscription.create(customer=customer_id, items=items)
        return sub["id"]

    def report_usage(self, subscription_item: str, qty: int):
        if not self.enabled:
            return
        self._stripe.SubscriptionItem.create_usage_record(
            subscription_item, quantity=qty, timestamp=int(time.time()))

    def verify_webhook(self, payload: bytes, sig_header: str) -> Optional[dict]:
        if not self.enabled or not CONFIG.stripe_webhook_secret:
            return None
        return self._stripe.Webhook.construct_event(
            payload, sig_header, CONFIG.stripe_webhook_secret)
