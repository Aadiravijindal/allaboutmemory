"""PART 3 — THE SYNC ENGINE. One brain, many hands.

  3.1 Automatic daily sync   -> pull_all() then project_all()
  3.2 Fight resolution       -> the vault's conflict logic (store._resolve)
  3.3 Per-AI diet            -> projection profiles from the Rulebook

Real deployments run each sync as a Temporal workflow (retries,
rate-limits, resumability). The logic below is that workflow's body.
"""
from __future__ import annotations

from .store import Vault
from .schema import MemoryUnit, MemoryStatus
from .connectors import ConnectorRegistry, Connector


class SyncEngine:
    def __init__(self, vault: Vault, registry: ConnectorRegistry):
        self.vault = vault
        self.registry = registry

    # ---- INBOUND: collect what every AI learned (Feature 2.3 collect) ---
    def pull(self, connector: Connector, actor: str = None) -> dict:
        actor = actor or f"connector:{connector.system}"
        token_key = f"in::{connector.system}"
        since = self._token(token_key)
        memories, new_token = connector.watch(since)
        added = 0
        for m in memories:
            self.vault.add(m, actor=actor)
            added += 1
        self._set_token(token_key, new_token)
        return {"system": connector.system, "pulled": added}

    def pull_all(self) -> list:
        return [self.pull(c) for c in self.registry.live().values()]

    # ---- OUTBOUND: deliver the shared brain, on each AI's diet (3.3) -----
    def project(self, connector: Connector) -> dict:
        target = connector.system
        prof = self.vault.policy.projection(target)
        namespaces = prof.get("namespaces")           # None => all
        min_trust = float(prof.get("min_trust", 0.0))
        exclude_bias = bool(prof.get("exclude_bias_risk", True))

        feed = []
        for m in self.vault.all_memories(status=MemoryStatus.ACTIVE.value):
            if m.provenance.get("source_system") == target:
                continue  # don't echo a system's own memories back to it
            if namespaces is not None and m.namespace not in namespaces:
                continue
            if m.trust < min_trust:
                continue
            if exclude_bias and m.bias_risk:
                continue
            feed.append(m)
        result = connector.load(feed)
        result["eligible"] = len(feed)
        return result

    def project_all(self) -> list:
        return [self.project(c) for c in self.registry.live().values()]

    # ---- full cycle: the "runs all day" loop body ------------------------
    def sync_once(self) -> dict:
        inbound = self.pull_all()
        outbound = self.project_all()
        return {"inbound": inbound, "outbound": outbound,
                "vault_counts": self.vault.counts()}

    # ---- cursors (stored in the vault) -----------------------------------
    def _token(self, key: str) -> str:
        row = self.vault.db.execute(
            "SELECT last_seq FROM cursors WHERE target=?", (key,)).fetchone()
        return "" if not row else str(row["last_seq"])

    def _set_token(self, key: str, token: str):
        # store ISO token in a side table keyed like a cursor
        self.vault.db.execute(
            "CREATE TABLE IF NOT EXISTS sync_tokens(k TEXT PRIMARY KEY, v TEXT)")
        self.vault.db.execute(
            "INSERT OR REPLACE INTO sync_tokens(k, v) VALUES (?,?)",
            (key, token))
        self.vault.db.commit()

    def _token(self, key: str) -> str:  # noqa: F811  (override with real impl)
        self.vault.db.execute(
            "CREATE TABLE IF NOT EXISTS sync_tokens(k TEXT PRIMARY KEY, v TEXT)")
        row = self.vault.db.execute(
            "SELECT v FROM sync_tokens WHERE k=?", (key,)).fetchone()
        return row["v"] if row else ""
