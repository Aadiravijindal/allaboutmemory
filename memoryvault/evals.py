"""Memory quality evals — a 'credit score' for the AI's brain.

Scores the vault on the dimensions that matter for reliability (the 2026
research: ~65% of enterprise AI failures come from stale/contradictory
memory, not weak models). Produces per-dimension scores + an overall grade,
and can run against a labeled eval set to report recall/precision over time.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .store import Vault
from .schema import MemoryStatus, conflict_key


class Evals:
    def __init__(self, vault: Vault):
        self.vault = vault

    def score(self) -> dict:
        active = self.vault.all_memories(status=MemoryStatus.ACTIVE.value)
        allm = self.vault.all_memories()
        n = len(active) or 1

        # freshness: share of active memory not past expiry
        now = datetime.now(timezone.utc)
        stale = 0
        for m in active:
            if m.expires_at:
                exp = datetime.fromisoformat(m.expires_at)
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if exp < now:
                    stale += 1
        freshness = 1 - stale / n

        # consistency: share of subject+attribute slots with a single value
        slots = {}
        for m in active:
            k = conflict_key(m)
            if k:
                slots.setdefault(k, set()).add(m.value.strip().lower())
        contradictions = sum(1 for vals in slots.values() if len(vals) > 1)
        consistency = 1 - (contradictions / (len(slots) or 1))

        # provenance coverage: share with a known source + employee
        with_prov = sum(1 for m in active
                        if (m.provenance or {}).get("source_system", "manual")
                        not in ("manual", "unknown", ""))
        provenance = with_prov / n

        # honesty: share NOT flagged as bias/yes-man
        bias = sum(1 for m in active if m.bias_risk)
        honesty = 1 - bias / n

        # hygiene: active vs superseded/duplicate noise
        superseded = sum(1 for m in allm
                         if m.status == MemoryStatus.SUPERSEDED.value)
        hygiene = n / (n + superseded)

        dims = {"freshness": freshness, "consistency": consistency,
                "provenance": provenance, "honesty": honesty, "hygiene": hygiene}
        overall = round(100 * (0.30 * freshness + 0.25 * consistency +
                               0.15 * provenance + 0.15 * honesty +
                               0.15 * hygiene))
        grade = ("A" if overall >= 90 else "B" if overall >= 78 else
                 "C" if overall >= 65 else "D" if overall >= 50 else "F")
        return {
            "overall": overall, "grade": grade,
            "dimensions": {k: round(v * 100) for k, v in dims.items()},
            "findings": {
                "stale_memories": stale,
                "contradicted_slots": contradictions,
                "bias_flagged": bias,
                "superseded_noise": superseded,
            },
        }

    def run_eval_set(self, cases: list, agent: str = "admin") -> dict:
        """Run labeled cases: [{'query':.., 'expect_substring':..}] and
        report recall (did the right memory surface in top results)."""
        hits = 0
        details = []
        for c in cases:
            res = self.vault.search(query=c["query"], agent=agent, limit=5,
                                    log=False)
            found = any(c["expect_substring"].lower() in m.content.lower()
                        for m in res)
            hits += 1 if found else 0
            details.append({"query": c["query"], "recall": found})
        recall = hits / (len(cases) or 1)
        return {"cases": len(cases), "recall_at_5": round(recall, 3),
                "details": details}
