"""Consent management — honor per-person consent for memory (GDPR/DPDP).

Tracks whether each data subject has consented to their data being kept as
AI memory, records grants/withdrawals with timestamps, and lets the vault
refuse or purge memory for anyone who has withdrawn consent.
"""
from __future__ import annotations

import json
import os
import time


class ConsentLedger:
    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, "consent.json")
        os.makedirs(data_dir, exist_ok=True)
        self._d = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.path):
            with open(self.path) as f:
                return json.load(f)
        return {}

    def _save(self):
        with open(self.path, "w") as f:
            json.dump(self._d, f, indent=2)

    def set(self, subject: str, granted: bool, basis: str = "consent",
            actor: str = "system"):
        rec = self._d.setdefault(subject, {"history": []})
        rec["granted"] = granted
        rec["basis"] = basis
        rec["updated_at"] = time.time()
        rec["history"].append({"granted": granted, "ts": time.time(),
                               "actor": actor, "basis": basis})
        self._save()
        return rec

    def has_consent(self, subject: str) -> bool:
        rec = self._d.get(subject)
        # default: allowed unless explicitly withdrawn (legitimate-interest
        # basis); a stricter deployment can flip this default.
        return True if rec is None else bool(rec.get("granted", True))

    def status(self, subject: str) -> dict:
        return self._d.get(subject, {"granted": True, "basis": "default"})

    def withdrawn(self) -> list:
        return [s for s, r in self._d.items() if not r.get("granted", True)]


def enforce_withdrawals(vault, ledger: "ConsentLedger", actor="consent") -> dict:
    """Purge memory for any subject who has withdrawn consent."""
    purged = []
    for subject in ledger.withdrawn():
        receipt = vault.erase_subject(subject, actor=actor)
        purged.append({"subject": subject,
                       "erased": len(receipt.get("memory_ids", []))})
    return {"subjects_purged": len(purged), "detail": purged}
