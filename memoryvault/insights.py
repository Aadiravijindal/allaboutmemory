"""PART 8 — INSIGHTS. The surprise gift.

  8.1 "What did our AI learn this quarter?" -> learned_summary()
  8.2 Signal alerts (repeated patterns)      -> signal_alerts()
  8.3 Blind-spot map (stale/thin areas)      -> blind_spots()

Plus the Health Score (Feature 5.3) which the Control Room shows as the
one number a boss watches.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone, timedelta

from .store import Vault
from .schema import MemoryStatus

_WORD = re.compile(r"[a-z0-9]{4,}")
_STOP = {"customer", "prefers", "agent", "there", "their", "about", "with",
         "that", "this", "from", "have", "will", "wants", "needs", "said",
         "they", "when", "what", "which", "into", "your", "ours", "than"}


def _keywords(text: str) -> list:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP]


class Insights:
    def __init__(self, vault: Vault):
        self.vault = vault

    # ---- 5.3 Health Score -----------------------------------------------
    def health_score(self) -> dict:
        counts = self.vault.counts()
        active = counts.get("active", 0)
        total = sum(counts.values()) or 1
        stale = counts.get("expired", 0)
        superseded = counts.get("superseded", 0)
        quarantined = counts.get("quarantined", 0)
        bias = sum(1 for m in self.vault.all_memories(
            status=MemoryStatus.ACTIVE.value) if m.bias_risk)

        # penalties: rot, contradictions, unreviewed junk, bias
        freshness = active / (active + stale) if (active + stale) else 1.0
        cleanliness = active / (active + superseded) if (active + superseded) else 1.0
        review = 1 - (quarantined / total)
        honesty = 1 - (bias / active) if active else 1.0
        score = round(100 * (0.35 * freshness + 0.30 * cleanliness +
                             0.15 * review + 0.20 * honesty))
        grade = ("A" if score >= 90 else "B" if score >= 75 else
                 "C" if score >= 60 else "D" if score >= 45 else "F")
        return {"score": score, "grade": grade,
                "freshness": round(freshness, 2),
                "cleanliness": round(cleanliness, 2),
                "review_backlog": quarantined,
                "bias_flags": bias, "active": active, "total": total}

    # ---- 8.1 -------------------------------------------------------------
    def learned_summary(self, days: int = 90) -> dict:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        kws = Counter()
        n = 0
        for m in self.vault.all_memories():
            if m.status == MemoryStatus.DELETED.value:
                continue
            ing = datetime.fromisoformat(m.ingested_at)
            if ing.tzinfo is None:
                ing = ing.replace(tzinfo=timezone.utc)
            if ing < cutoff:
                continue
            n += 1
            kws.update(_keywords(m.content))
        return {"window_days": days, "memories_learned": n,
                "top_themes": kws.most_common(10)}

    # ---- 8.2 -------------------------------------------------------------
    def signal_alerts(self, min_count: int = 3) -> list:
        by_key = Counter()
        examples = {}
        for m in self.vault.all_memories(status=MemoryStatus.ACTIVE.value):
            for kw in set(_keywords(m.content)):
                by_key[kw] += 1
                examples.setdefault(kw, m.content)
        alerts = []
        for kw, count in by_key.most_common(20):
            if count >= min_count:
                alerts.append({"pattern": kw, "count": count,
                               "example": examples[kw]})
        return alerts

    # ---- 8.3 -------------------------------------------------------------
    def blind_spots(self) -> dict:
        now = datetime.now(timezone.utc)
        by_ns_age = {}
        for m in self.vault.all_memories(status=MemoryStatus.ACTIVE.value):
            occ = datetime.fromisoformat(m.occurred_at)
            if occ.tzinfo is None:
                occ = occ.replace(tzinfo=timezone.utc)
            age = (now - occ).days
            by_ns_age.setdefault(m.namespace, []).append(age)
        report = {}
        for ns, ages in by_ns_age.items():
            avg = sum(ages) / len(ages)
            report[ns] = {"count": len(ages), "avg_age_days": round(avg),
                          "risk": "high" if avg > 180 else
                                  "medium" if avg > 90 else "low"}
        return report
