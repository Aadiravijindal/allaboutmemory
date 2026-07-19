"""Memory ROI — turn the vault into a dollar number (the CFO's question).

Computes value the memory layer creates: re-learning avoided, hours saved,
duplicate questions deflected, stale/poison incidents prevented. Uses the
vault's own counts + audit events, with tunable rates a customer sets once.
"""
from __future__ import annotations

from .store import Vault

# Default value assumptions (a customer tunes these in settings).
DEFAULTS = {
    "minutes_saved_per_reuse": 6,       # each memory reused instead of re-asked
    "loaded_hourly_cost": 60,           # blended $/hour of an employee
    "onboarding_days_saved_per_agent": 3,
    "incident_cost": 12000,             # avg cost of a poisoned/wrong-memory incident
}


class ROI:
    def __init__(self, vault: Vault, rates: dict = None):
        self.vault = vault
        self.rates = {**DEFAULTS, **(rates or {})}

    def _retrieval_count(self) -> int:
        row = self.vault.db.execute("SELECT COUNT(*) n FROM retrievals").fetchone()
        return row["n"] if row else 0

    def _event_count(self, action_prefix: str) -> int:
        rows = self.vault.db.execute("SELECT action FROM events").fetchall()
        return sum(1 for r in rows if r["action"].startswith(action_prefix))

    def summary(self) -> dict:
        counts = self.vault.counts()
        active = counts.get("active", 0)
        reuses = self._retrieval_count()
        forgotten = counts.get("expired", 0) + counts.get("superseded", 0)
        # incidents prevented = quarantined (poison/policy caught before harm)
        incidents_prevented = counts.get("quarantined", 0)
        deduped = self._event_count("dedupe_merged")

        r = self.rates
        hours_saved = reuses * r["minutes_saved_per_reuse"] / 60
        reuse_value = round(hours_saved * r["loaded_hourly_cost"])
        incident_value = incidents_prevented * r["incident_cost"]
        # cleanliness dividend: duplicates removed → cheaper, faster retrieval
        cleanup_value = round(deduped * r["minutes_saved_per_reuse"] / 60
                              * r["loaded_hourly_cost"])
        total = reuse_value + incident_value + cleanup_value

        return {
            "total_value_usd": total,
            "breakdown": {
                "reuse_value_usd": reuse_value,
                "incidents_prevented_usd": incident_value,
                "cleanup_value_usd": cleanup_value,
            },
            "drivers": {
                "memories_active": active,
                "memories_reused": reuses,
                "hours_saved": round(hours_saved, 1),
                "incidents_prevented": incidents_prevented,
                "duplicates_removed": deduped,
                "facts_retired": forgotten,
            },
            "assumptions": self.rates,
        }
