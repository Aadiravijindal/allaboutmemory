"""PART 1 — THE VAULT. One store, event-sourced, in the customer's cloud.

SQLite for zero-config dev/demo; the SQL is deliberately portable so a
Postgres backend is a driver swap, not a rewrite.

Design decision that powers half the product: NOTHING is overwritten.
Every change appends an event carrying a full snapshot, hash-chained to
the previous event. From that one decision we get, for free:
  1.3 the diary (history)  ->  events table
  the undo button          ->  rollback restores a snapshot
  6.4 the flight recorder  ->  retrievals table
  6.3 tamper-proof receipts->  the hash chain
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from .schema import (MemoryUnit, MemoryStatus, conflict_key, now_iso)
from .policy import Policy
from .crypto import Cipher, LocalKeyProvider, HAVE_CRYPTO


class Vault:
    def __init__(self, path: str = "vault.db", policy: Optional[Policy] = None,
                 encrypt: bool = False):
        self.path = path
        self.policy = policy or Policy()
        provider = None
        if encrypt and HAVE_CRYPTO:
            provider = LocalKeyProvider(path + ".key")
        self.cipher = Cipher(provider)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._init_schema()

    # ------------------------------------------------------------------ DDL
    def _init_schema(self):
        c = self.db
        c.executescript("""
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY, content TEXT, type TEXT, namespace TEXT,
            subject TEXT, attribute TEXT, value TEXT, entities TEXT,
            tags TEXT, trust REAL, status TEXT, decay_class TEXT,
            occurred_at TEXT, ingested_at TEXT, expires_at TEXT,
            provenance TEXT, version INTEGER, supersedes TEXT,
            bias_risk INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_mem_subject ON memories(subject, attribute);
        CREATE INDEX IF NOT EXISTS idx_mem_status ON memories(status);
        CREATE INDEX IF NOT EXISTS idx_mem_ns ON memories(namespace);

        CREATE TABLE IF NOT EXISTS events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, actor TEXT, action TEXT, memory_id TEXT,
            snapshot TEXT, prev_hash TEXT, hash TEXT
        );

        CREATE TABLE IF NOT EXISTS retrievals (
            id TEXT PRIMARY KEY, ts TEXT, agent TEXT, query TEXT,
            memory_ids TEXT, context TEXT
        );

        CREATE TABLE IF NOT EXISTS receipts (
            id TEXT PRIMARY KEY, ts TEXT, kind TEXT, payload TEXT, hash TEXT
        );

        CREATE TABLE IF NOT EXISTS cursors (
            target TEXT PRIMARY KEY, last_seq INTEGER
        );
        """)
        try:
            c.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS mem_fts
                         USING fts5(id UNINDEXED, text)""")
            self.have_fts = True
        except sqlite3.OperationalError:
            self.have_fts = False
        c.commit()

    # ------------------------------------------------------- event chain
    def _last_hash(self) -> str:
        row = self.db.execute(
            "SELECT hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        return row["hash"] if row else "genesis"

    def _append_event(self, actor: str, action: str, m: MemoryUnit) -> int:
        prev = self._last_hash()
        snapshot = m.to_json()
        h = hashlib.sha256((prev + action + snapshot).encode()).hexdigest()
        cur = self.db.execute(
            "INSERT INTO events(ts, actor, action, memory_id, snapshot,"
            " prev_hash, hash) VALUES (?,?,?,?,?,?,?)",
            (now_iso(), actor, action, m.id, snapshot, prev, h))
        return cur.lastrowid

    def verify_chain(self) -> bool:
        """Tamper-evidence check over the whole event log."""
        prev = "genesis"
        for row in self.db.execute("SELECT * FROM events ORDER BY seq"):
            expect = hashlib.sha256(
                (prev + row["action"] + row["snapshot"]).encode()).hexdigest()
            if expect != row["hash"] or row["prev_hash"] != prev:
                return False
            prev = row["hash"]
        return True

    # ------------------------------------------------------------ persist
    def _put_row(self, m: MemoryUnit):
        d = m.to_dict()
        d["content"] = self.cipher.encrypt(d["content"])
        d["entities"] = json.dumps(d["entities"])
        d["tags"] = json.dumps(d["tags"])
        d["provenance"] = json.dumps(d["provenance"])
        d["bias_risk"] = int(d["bias_risk"])
        cols = ",".join(d.keys())
        marks = ",".join("?" * len(d))
        self.db.execute(
            f"INSERT OR REPLACE INTO memories({cols}) VALUES ({marks})",
            list(d.values()))
        if self.have_fts:
            self.db.execute("DELETE FROM mem_fts WHERE id=?", (m.id,))
            text = " ".join([m.content, m.subject, m.attribute, m.value,
                             " ".join(m.entities), " ".join(m.tags)])
            self.db.execute("INSERT INTO mem_fts(id, text) VALUES (?,?)",
                            (m.id, text))

    def _row_to_mem(self, row) -> MemoryUnit:
        d = dict(row)
        d["content"] = self.cipher.decrypt(d["content"])
        d["entities"] = json.loads(d["entities"] or "[]")
        d["tags"] = json.loads(d["tags"] or "[]")
        d["provenance"] = json.loads(d["provenance"] or "{}")
        d["bias_risk"] = bool(d["bias_risk"])
        return MemoryUnit.from_dict(d)

    # ----------------------------------------------------------- write API
    def add(self, m: MemoryUnit, actor: str = "system") -> MemoryUnit:
        """Write path: Rulebook check -> conflict fight -> event -> index."""
        # 5.4 Approval Room decision
        if m.status == MemoryStatus.ACTIVE.value:
            m.status = self.policy.evaluate_write(m)
        # 6.2 policy TTL overrides
        ttl = self.policy.ttl_override_days(m)
        if ttl is not None:
            from datetime import timedelta
            base = datetime.fromisoformat(m.occurred_at)
            if base.tzinfo is None:
                base = base.replace(tzinfo=timezone.utc)
            m.expires_at = (base + timedelta(days=ttl)).isoformat()
        # 3.2 / 7.3 conflict fight (only active memories fight)
        if m.status == MemoryStatus.ACTIVE.value:
            self._resolve_conflicts(m, actor)
        self._put_row(m)
        self._append_event(actor, "add", m)
        self.db.commit()
        return m

    def _resolve_conflicts(self, incoming: MemoryUnit, actor: str):
        key = conflict_key(incoming)
        if not key:
            return
        rows = self.db.execute(
            "SELECT * FROM memories WHERE lower(subject)=? AND"
            " lower(attribute)=? AND status=?",
            (key[0], key[1], MemoryStatus.ACTIVE.value)).fetchall()
        from .entities import conflict_strategy
        strategy = conflict_strategy(incoming.attribute)
        for row in rows:
            existing = self._row_to_mem(row)
            if existing.value.strip().lower() == incoming.value.strip().lower():
                continue  # same claim, not a fight — dedupe handles it
            # Per-attribute policy (Feature 3.2, upgraded): mutable facts
            # (plan, address, status) use recency; identity/money facts
            # (ssn, invoice routing) trust the verified source. Loser goes to
            # history, never lost. Low-trust sources are gated earlier by the
            # Approval Room, so anything active here is eligible to win.
            if strategy == "trust":
                inc_score = (incoming.trust, incoming.occurred_at)
                ex_score = (existing.trust, existing.occurred_at)
            else:  # recency
                inc_score = (incoming.occurred_at, incoming.trust)
                ex_score = (existing.occurred_at, existing.trust)
            if inc_score >= ex_score:
                existing.status = MemoryStatus.SUPERSEDED.value
                incoming.supersedes = existing.id
                self._put_row(existing)
                self._append_event(actor, "superseded_by_conflict", existing)
            else:
                incoming.status = MemoryStatus.SUPERSEDED.value
                incoming.supersedes = existing.id

    def update(self, memory_id: str, changes: dict,
               actor: str = "system") -> Optional[MemoryUnit]:
        m = self.get(memory_id)
        if not m:
            return None
        for k, v in changes.items():
            if hasattr(m, k) and k != "id":
                setattr(m, k, v)
        m.version += 1
        self._put_row(m)
        self._append_event(actor, "update", m)
        self.db.commit()
        return m

    # ---- 6.3 delete-with-receipt -----------------------------------------
    def delete(self, memory_id: str, actor: str = "system",
               cascade_results: Optional[dict] = None) -> Optional[dict]:
        m = self.get(memory_id)
        if not m:
            return None
        m.status = MemoryStatus.DELETED.value
        m.content = "[deleted]"
        self._put_row(m)
        seq = self._append_event(actor, "delete", m)
        receipt = self._issue_receipt("deletion", {
            "memory_id": memory_id, "actor": actor, "event_seq": seq,
            "cascade": cascade_results or {"vault": "ok"},
        })
        self.db.commit()
        return receipt

    def erase_subject(self, subject: str, actor: str = "system",
                      cascade_results: Optional[dict] = None) -> dict:
        """GDPR 'erase me': everything about one subject, one receipt."""
        rows = self.db.execute(
            "SELECT id FROM memories WHERE subject=? AND status!=?",
            (subject, MemoryStatus.DELETED.value)).fetchall()
        ids = [r["id"] for r in rows]
        for mid in ids:
            m = self.get(mid)
            m.status = MemoryStatus.DELETED.value
            m.content = "[deleted]"
            self._put_row(m)
            self._append_event(actor, "delete", m)
        receipt = self._issue_receipt("subject_erasure", {
            "subject": subject, "memory_ids": ids, "actor": actor,
            "cascade": cascade_results or {"vault": "ok"},
        })
        self.db.commit()
        return receipt

    def _issue_receipt(self, kind: str, payload: dict) -> dict:
        payload = {**payload, "ts": now_iso(),
                   "chain_head": self._last_hash()}
        body = json.dumps(payload, sort_keys=True)
        h = hashlib.sha256(body.encode()).hexdigest()
        rid = uuid.uuid4().hex
        self.db.execute(
            "INSERT INTO receipts(id, ts, kind, payload, hash)"
            " VALUES (?,?,?,?,?)", (rid, payload["ts"], kind, body, h))
        return {"id": rid, "kind": kind, "hash": h, **payload}

    # --------------------------------------------------------- 1.3 history
    def history(self, memory_id: str) -> list:
        rows = self.db.execute(
            "SELECT seq, ts, actor, action, snapshot FROM events"
            " WHERE memory_id=? ORDER BY seq", (memory_id,)).fetchall()
        return [{"seq": r["seq"], "ts": r["ts"], "actor": r["actor"],
                 "action": r["action"],
                 "snapshot": json.loads(r["snapshot"])} for r in rows]

    def rollback(self, memory_id: str, to_seq: int,
                 actor: str = "system") -> Optional[MemoryUnit]:
        """The undo button: restore a memory to any past state."""
        row = self.db.execute(
            "SELECT snapshot FROM events WHERE memory_id=? AND seq<=?"
            " ORDER BY seq DESC LIMIT 1", (memory_id, to_seq)).fetchone()
        if not row:
            return None
        m = MemoryUnit.from_json(row["snapshot"])
        m.version += 1
        self._put_row(m)
        self._append_event(actor, f"rollback_to_seq_{to_seq}", m)
        self.db.commit()
        return m

    def rollback_since(self, iso_ts: str, actor: str = "system") -> int:
        """Vault-wide undo: restore every memory changed after a moment.
        'Bad info got in on Tuesday? Roll back to Monday's brain.'"""
        changed = self.db.execute(
            "SELECT DISTINCT memory_id FROM events WHERE ts>?",
            (iso_ts,)).fetchall()
        count = 0
        for row in changed:
            mid = row["memory_id"]
            prior = self.db.execute(
                "SELECT snapshot FROM events WHERE memory_id=? AND ts<=?"
                " ORDER BY seq DESC LIMIT 1", (mid, iso_ts)).fetchone()
            if prior:
                m = MemoryUnit.from_json(prior["snapshot"])
                m.version += 1
                self._put_row(m)
                self._append_event(actor, f"rollback_to_{iso_ts}", m)
            else:  # didn't exist yet -> tombstone it
                m = self.get(mid)
                if m:
                    m.status = MemoryStatus.DELETED.value
                    self._put_row(m)
                    self._append_event(actor, f"rollback_to_{iso_ts}", m)
            count += 1
        self.db.commit()
        return count

    # ------------------------------------------------------------ read API
    def get(self, memory_id: str) -> Optional[MemoryUnit]:
        row = self.db.execute(
            "SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        return self._row_to_mem(row) if row else None

    def search(self, query: str = "", agent: str = "admin",
               namespace: Optional[str] = None, status: str = "active",
               subject: Optional[str] = None, limit: int = 50,
               log: bool = True, context: str = "") -> list:
        """Hybrid search with ACL walls + flight-recorder logging."""
        allowed = self.policy.allowed_namespaces(agent)
        ids = None
        if query and self.have_fts:
            safe = " ".join(t for t in query.replace('"', " ").split())
            try:
                rows = self.db.execute(
                    "SELECT id FROM mem_fts WHERE mem_fts MATCH ?"
                    " LIMIT 500", (safe,)).fetchall()
                ids = [r["id"] for r in rows]
            except sqlite3.OperationalError:
                ids = None
        sql = "SELECT * FROM memories WHERE 1=1"
        args: list = []
        if status and status != "all":
            sql += " AND status=?"; args.append(status)
        if namespace:
            sql += " AND namespace=?"; args.append(namespace)
        if subject:
            sql += " AND subject=?"; args.append(subject)
        if allowed is not None:
            sql += f" AND namespace IN ({','.join('?'*len(allowed))})"
            args.extend(allowed)
        if ids is not None:
            if not ids:
                return []
            sql += f" AND id IN ({','.join('?'*len(ids))})"
            args.extend(ids)
        elif query:  # LIKE fallback when FTS unavailable
            sql += " AND (content LIKE ? OR subject LIKE ? OR value LIKE ?)"
            like = f"%{query}%"
            args.extend([like, like, like])
        sql += " ORDER BY trust DESC, occurred_at DESC LIMIT ?"
        args.append(limit)
        rows = self.db.execute(sql, args).fetchall()
        results = [self._row_to_mem(r) for r in rows]
        if log and results:
            self._log_retrieval(agent, query, [m.id for m in results], context)
        return results

    # ---- 6.4 the flight recorder ------------------------------------------
    def _log_retrieval(self, agent: str, query: str, ids: list, context: str):
        self.db.execute(
            "INSERT INTO retrievals(id, ts, agent, query, memory_ids, context)"
            " VALUES (?,?,?,?,?,?)",
            (uuid.uuid4().hex, now_iso(), agent, query, json.dumps(ids),
             context))
        self.db.commit()

    def retrievals(self, memory_id: Optional[str] = None,
                   agent: Optional[str] = None, limit: int = 100) -> list:
        rows = self.db.execute(
            "SELECT * FROM retrievals ORDER BY ts DESC LIMIT ?",
            (limit * 5,)).fetchall()
        out = []
        for r in rows:
            ids = json.loads(r["memory_ids"])
            if memory_id and memory_id not in ids:
                continue
            if agent and r["agent"] != agent:
                continue
            out.append({"id": r["id"], "ts": r["ts"], "agent": r["agent"],
                        "query": r["query"], "memory_ids": ids,
                        "context": r["context"]})
            if len(out) >= limit:
                break
        return out

    # ------------------------------------------------- Approval Room (5.4)
    def quarantine_list(self) -> list:
        rows = self.db.execute(
            "SELECT * FROM memories WHERE status=? ORDER BY ingested_at DESC",
            (MemoryStatus.QUARANTINED.value,)).fetchall()
        return [self._row_to_mem(r) for r in rows]

    def approve(self, memory_id: str, actor: str = "reviewer"):
        m = self.get(memory_id)
        if not m or m.status != MemoryStatus.QUARANTINED.value:
            return None
        m.status = MemoryStatus.ACTIVE.value
        self._resolve_conflicts(m, actor)
        self._put_row(m)
        self._append_event(actor, "approve", m)
        self.db.commit()
        return m

    def reject(self, memory_id: str, actor: str = "reviewer"):
        m = self.get(memory_id)
        if not m:
            return None
        m.status = MemoryStatus.DELETED.value
        self._put_row(m)
        self._append_event(actor, "reject", m)
        self.db.commit()
        return m

    # ----------------------------------------------------------- utilities
    def all_memories(self, status: Optional[str] = None) -> list:
        sql, args = "SELECT * FROM memories", []
        if status:
            sql += " WHERE status=?"; args.append(status)
        return [self._row_to_mem(r) for r in self.db.execute(sql, args)]

    def counts(self) -> dict:
        rows = self.db.execute(
            "SELECT status, COUNT(*) n FROM memories GROUP BY status")
        return {r["status"]: r["n"] for r in rows}

    def events_since(self, seq: int) -> list:
        rows = self.db.execute(
            "SELECT * FROM events WHERE seq>? ORDER BY seq", (seq,))
        return [dict(r) for r in rows]

    def get_cursor(self, target: str) -> int:
        row = self.db.execute(
            "SELECT last_seq FROM cursors WHERE target=?", (target,)).fetchone()
        return row["last_seq"] if row else 0

    def set_cursor(self, target: str, seq: int):
        self.db.execute(
            "INSERT OR REPLACE INTO cursors(target, last_seq) VALUES (?,?)",
            (target, seq))
        self.db.commit()

    def last_seq(self) -> int:
        row = self.db.execute("SELECT MAX(seq) m FROM events").fetchone()
        return row["m"] or 0

    def receipts_list(self, limit: int = 100) -> list:
        rows = self.db.execute(
            "SELECT * FROM receipts ORDER BY ts DESC LIMIT ?", (limit,))
        return [{"id": r["id"], "ts": r["ts"], "kind": r["kind"],
                 "hash": r["hash"], "payload": json.loads(r["payload"])}
                for r in rows]
