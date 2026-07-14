"""PART 7 — THE CLEANER. The brain that doesn't rot.

Runs as background workers (nightly job queue in production). Every pass
is safe: nothing is hard-deleted, losers become SUPERSEDED/EXPIRED and
stay in history.

  7.1 Duplicate remover   -> dedupe()
  7.2 Freshness keeper     -> expire_stale()
  7.3 Contradiction fixer  -> resolve_contradictions()
  7.4 Yes-man filter       -> flag_bias()
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from .store import Vault
from .schema import MemoryStatus, MemoryType, conflict_key
from .embeddings import get_embedder
from .entities import conflict_strategy

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set:
    return set(_WORD.findall(text.lower()))


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# Opinion/bias cues for the yes-man filter (7.4). A classifier in prod.
_BIAS_CUES = ["i think", "i believe", "in my opinion", "hate", "love",
              "is the best", "is the worst", "is trash", "is amazing",
              "always right", "obviously", "everyone knows", "sucks",
              "terrible", "prefer x over", "better than", "worse than"]


class Cleaner:
    def __init__(self, vault: Vault, embedder=None,
                 sem_threshold: float = 0.86, lex_threshold: float = 0.82):
        self.vault = vault
        self.embedder = embedder or get_embedder()
        self.sem_threshold = sem_threshold
        self.lex_threshold = lex_threshold

    # ---- 7.1 : embedding + lexical + same-slot dedupe --------------------
    def dedupe(self, actor: str = "cleaner") -> dict:
        active = self.vault.all_memories(status=MemoryStatus.ACTIVE.value)
        vecs = {m.id: self.embedder.embed(m.content) for m in active}
        removed, seen = 0, []
        for m in sorted(active, key=lambda x: (x.trust, x.occurred_at),
                        reverse=True):
            dup_of = None
            for keeper in seen:
                same_slot = (conflict_key(m) and
                             conflict_key(m) == conflict_key(keeper) and
                             m.value.strip().lower() ==
                             keeper.value.strip().lower())
                sem = self.embedder.cosine(vecs[m.id], vecs[keeper.id])
                lex = _jaccard(m.content, keeper.content)
                # semantic OR lexical near-duplicate, or identical slot/value
                if same_slot or sem >= self.sem_threshold or \
                        lex >= self.lex_threshold:
                    dup_of = keeper
                    break
            if dup_of:
                m.status = MemoryStatus.SUPERSEDED.value
                m.supersedes = dup_of.id
                self.vault._put_row(m)
                self.vault._append_event(actor, "dedupe_merged", m)
                removed += 1
            else:
                seen.append(m)
        self.vault.db.commit()
        return {"checked": len(active), "merged": removed}

    # ---- 7.2 -------------------------------------------------------------
    def expire_stale(self, actor: str = "cleaner", now=None) -> dict:
        now = now or datetime.now(timezone.utc)
        expired = 0
        for m in self.vault.all_memories(status=MemoryStatus.ACTIVE.value):
            if not m.expires_at:
                continue
            exp = datetime.fromisoformat(m.expires_at)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < now:
                m.status = MemoryStatus.EXPIRED.value
                self.vault._put_row(m)
                self.vault._append_event(actor, "expired_stale", m)
                expired += 1
        self.vault.db.commit()
        return {"expired": expired}

    # ---- 7.3 -------------------------------------------------------------
    def resolve_contradictions(self, actor: str = "cleaner") -> dict:
        active = self.vault.all_memories(status=MemoryStatus.ACTIVE.value)
        groups = {}
        for m in active:
            k = conflict_key(m)
            if k:
                groups.setdefault(k, []).append(m)
        resolved, ambiguous = 0, 0
        for k, group in groups.items():
            values = {m.value.strip().lower() for m in group}
            if len(values) <= 1:
                continue
            # per-attribute policy: recency vs trust (Feature 3.2, upgraded)
            strategy = conflict_strategy(group[0].attribute)
            if strategy == "trust":
                keyf = lambda x: (x.trust, x.occurred_at)
            else:
                keyf = lambda x: (x.occurred_at, x.trust)
            winner = max(group, key=keyf)
            close = [m for m in group if m.id != winner.id and
                     keyf(m) == keyf(winner)]
            for m in group:
                if m.id == winner.id:
                    continue
                m.status = MemoryStatus.SUPERSEDED.value
                m.supersedes = winner.id
                self.vault._put_row(m)
                self.vault._append_event(actor, "contradiction_resolved", m)
                resolved += 1
            if close:
                ambiguous += 1  # would surface to a human in the Control Room
        self.vault.db.commit()
        return {"resolved": resolved, "needs_human_review": ambiguous}

    # ---- 7.4 -------------------------------------------------------------
    def flag_bias(self, actor: str = "cleaner") -> dict:
        flagged = 0
        for m in self.vault.all_memories(status=MemoryStatus.ACTIVE.value):
            text = m.content.lower()
            looks_opinion = (m.type == MemoryType.OPINION.value or
                             any(cue in text for cue in _BIAS_CUES))
            if looks_opinion and not m.bias_risk:
                m.bias_risk = True
                self.vault._put_row(m)
                self.vault._append_event(actor, "flagged_bias_risk", m)
                flagged += 1
        self.vault.db.commit()
        return {"flagged": flagged}

    def run_all(self) -> dict:
        return {
            "dedupe": self.dedupe(),
            "expire": self.expire_stale(),
            "contradictions": self.resolve_contradictions(),
            "bias": self.flag_bias(),
        }
