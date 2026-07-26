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

from .schema import (MemoryUnit, MemoryStatus, Conversation, conflict_key,
                     now_iso)
from .policy import Policy
from .crypto import Cipher, LocalKeyProvider, HAVE_CRYPTO


class Vault:
    def __init__(self, path: str = "vault.db", policy: Optional[Policy] = None,
                 encrypt: bool = False, policy_guard=None, redact_pii: bool = False,
                 zero_retention: bool = False, event_hook=None):
        self.path = path
        self.policy = policy or Policy()
        # enterprise governance hooks (optional; lazy defaults)
        self.policy_guard = policy_guard
        self.redact_pii = redact_pii
        self.zero_retention = zero_retention   # ZDR: store metadata, not content
        # real-time write-back: fired on every committed write (add/update/
        # delete). Kept as a plain callback so the store stays decoupled from
        # the RealtimeBus. Never lets a subscriber error break a write.
        self.event_hook = event_hook
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
            bias_risk INTEGER DEFAULT 0,
            tier TEXT DEFAULT 'team', flags TEXT DEFAULT '[]',
            legal_hold INTEGER DEFAULT 0, pii_types TEXT DEFAULT '[]',
            redacted INTEGER DEFAULT 0, classification TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_mem_subject ON memories(subject, attribute);
        CREATE INDEX IF NOT EXISTS idx_mem_status ON memories(status);
        CREATE INDEX IF NOT EXISTS idx_mem_ns ON memories(namespace);
        CREATE INDEX IF NOT EXISTS idx_mem_tier ON memories(tier);

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

        -- the archive half: whole conversations, kept verbatim
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY, external_id TEXT, source_system TEXT,
            title TEXT, messages TEXT, subjects TEXT, namespace TEXT,
            employee TEXT, employee_email TEXT, department TEXT,
            started_at TEXT, ingested_at TEXT, expires_at TEXT,
            retention_days INTEGER, status TEXT, classification TEXT,
            pii_types TEXT, redacted INTEGER DEFAULT 0,
            legal_hold INTEGER DEFAULT 0, flags TEXT,
            fact_ids TEXT, message_count INTEGER, tokens_estimate INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_conv_ext ON conversations(external_id);
        CREATE INDEX IF NOT EXISTS idx_conv_emp ON conversations(employee);
        CREATE INDEX IF NOT EXISTS idx_conv_src ON conversations(source_system);
        CREATE INDEX IF NOT EXISTS idx_conv_status ON conversations(status);
        """)
        try:
            c.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS mem_fts
                         USING fts5(id UNINDEXED, text)""")
            c.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS conv_fts
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
        d["flags"] = json.dumps(d.get("flags", []))
        d["pii_types"] = json.dumps(d.get("pii_types", []))
        d["legal_hold"] = int(d.get("legal_hold", False))
        d["redacted"] = int(d.get("redacted", False))
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
        d["flags"] = json.loads(d.get("flags") or "[]")
        d["pii_types"] = json.loads(d.get("pii_types") or "[]")
        d["legal_hold"] = bool(d.get("legal_hold"))
        d["redacted"] = bool(d.get("redacted"))
        return MemoryUnit.from_dict(d)

    # ----------------------------------------------------------- write API
    def add(self, m: MemoryUnit, actor: str = "system") -> MemoryUnit:
        """Write path: PII scan -> Policy Guard -> Rulebook -> conflict ->
        event -> index. Enterprise governance runs before anything is stored."""
        # ---- PII detection & redaction (enterprise) ----
        from .pii import scan_and_maybe_redact
        m.content, m.pii_types, m.redacted = scan_and_maybe_redact(
            m.content, self.redact_pii)
        if m.pii_types and "pii" not in m.flags:
            m.flags = list(m.flags) + ["pii"]
        # ---- data classification (sensitivity level) ----
        from .classification import classify
        if not m.classification:
            m.classification = classify(m)
        # ---- Zero-Data-Retention: keep governance metadata, drop content ----
        if self.zero_retention:
            m.content = "[zero-retention: content not persisted]"
            m.redacted = True
        # ---- Policy Guard: flag company-rule violations (enterprise) ----
        if self.policy_guard is not None:
            violations = self.policy_guard.evaluate(m)
            if violations:
                m.flags = list(m.flags) + [f"policy:{v.rule_id}" for v in violations]
                # a critical violation quarantines the memory for review
                if any(v.severity == "critical" for v in violations) and \
                        m.status == MemoryStatus.ACTIVE.value:
                    m.status = MemoryStatus.QUARANTINED.value
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
        # only surface memories that are actually live (not quarantined)
        if m.status == MemoryStatus.ACTIVE.value:
            self._fire("add", m)
        return m

    def _fire(self, action: str, m: MemoryUnit):
        """Notify the real-time bus of a committed write. A misbehaving
        subscriber must never break the write, so failures are swallowed."""
        if self.event_hook is None:
            return
        try:
            self.event_hook(action, m.to_dict())
        except Exception:
            pass

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
        self._fire("update", m)
        return m

    # ---- 6.3 delete-with-receipt -----------------------------------------
    def delete(self, memory_id: str, actor: str = "system",
               cascade_results: Optional[dict] = None) -> Optional[dict]:
        m = self.get(memory_id)
        if not m:
            return None
        # legal hold: frozen for litigation, cannot be deleted
        if getattr(m, "legal_hold", False):
            return {"blocked": True, "reason": "memory is under legal hold",
                    "memory_id": memory_id}
        m.status = MemoryStatus.DELETED.value
        m.content = "[deleted]"
        self._put_row(m)
        seq = self._append_event(actor, "delete", m)
        receipt = self._issue_receipt("deletion", {
            "memory_id": memory_id, "actor": actor, "event_seq": seq,
            "cascade": cascade_results or {"vault": "ok"},
        })
        self.db.commit()
        self._fire("delete", m)
        return receipt

    def erase_subject(self, subject: str, actor: str = "system",
                      cascade_results: Optional[dict] = None) -> dict:
        """GDPR 'erase me': everything about one subject, one receipt."""
        rows = self.db.execute(
            "SELECT id FROM memories WHERE subject=? AND status!=?",
            (subject, MemoryStatus.DELETED.value)).fetchall()
        erased, skipped_hold = [], []
        for r in rows:
            m = self.get(r["id"])
            if getattr(m, "legal_hold", False):
                skipped_hold.append(m.id)   # litigation freeze wins over erasure
                continue
            m.status = MemoryStatus.DELETED.value
            m.content = "[deleted]"
            self._put_row(m)
            self._append_event(actor, "delete", m)
            erased.append(m.id)
        # erasure has to reach the transcripts too, or the person isn't erased
        convs_erased = []
        for c in self.conversations_for_subject(subject):
            if c.legal_hold:
                skipped_hold.append(c.id)
                continue
            c.status = MemoryStatus.DELETED.value
            c.messages = [{"role": mm.get("role", "?"), "content": "[deleted]",
                           "ts": mm.get("ts", now_iso())} for mm in c.messages]
            self._put_conv_row(c)
            self._append_event(actor, "conversation_deleted", c)
            convs_erased.append(c.id)
        receipt = self._issue_receipt("subject_erasure", {
            "subject": subject, "memory_ids": erased,
            "conversation_ids": convs_erased,
            "skipped_legal_hold": skipped_hold, "actor": actor,
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

    # ==================================================================
    #  THE ARCHIVE — whole conversations, under the same governance
    # ==================================================================
    def _put_conv_row(self, c: Conversation):
        d = c.to_dict()
        d["messages"] = self.cipher.encrypt(json.dumps(d["messages"]))
        d["subjects"] = json.dumps(d["subjects"])
        d["pii_types"] = json.dumps(d["pii_types"])
        d["flags"] = json.dumps(d["flags"])
        d["fact_ids"] = json.dumps(d["fact_ids"])
        d["redacted"] = int(d["redacted"])
        d["legal_hold"] = int(d["legal_hold"])
        cols = ",".join(d.keys())
        marks = ",".join("?" * len(d))
        self.db.execute(
            f"INSERT OR REPLACE INTO conversations({cols}) VALUES ({marks})",
            list(d.values()))
        if self.have_fts:
            self.db.execute("DELETE FROM conv_fts WHERE id=?", (c.id,))
            text = " ".join([c.title, c.employee, c.department,
                             " ".join(c.subjects), c.transcript()])
            self.db.execute("INSERT INTO conv_fts(id, text) VALUES (?,?)",
                            (c.id, text))

    def _row_to_conv(self, row) -> Conversation:
        d = dict(row)
        d["messages"] = json.loads(self.cipher.decrypt(d["messages"]) or "[]")
        d["subjects"] = json.loads(d["subjects"] or "[]")
        d["pii_types"] = json.loads(d["pii_types"] or "[]")
        d["flags"] = json.loads(d["flags"] or "[]")
        d["fact_ids"] = json.loads(d["fact_ids"] or "[]")
        d["redacted"] = bool(d["redacted"])
        d["legal_hold"] = bool(d["legal_hold"])
        return Conversation.from_dict(d)

    def add_conversation(self, conv: Conversation,
                         actor: str = "system") -> Conversation:
        """Store a whole chat. Same write path as a fact: sensitive data is
        scanned, the chat is classified, company rules are checked against the
        transcript, and the whole thing is sealed into the event chain.

        Re-ingesting the same chat updates it in place instead of duplicating,
        so a second rescue or a daily sync doesn't fork the archive."""
        existing = (self.conversation_by_external(conv.external_id,
                                                  conv.source_system)
                    if conv.external_id else None)
        action = "conversation_stored"
        if existing:
            action = "conversation_updated"
            conv.id = existing.id                       # keep the stable id
            conv.ingested_at = existing.ingested_at
            # never lose governance state that was applied to the old copy
            conv.fact_ids = sorted(set(existing.fact_ids) | set(conv.fact_ids))
            conv.legal_hold = existing.legal_hold or conv.legal_hold
            if existing.status == MemoryStatus.DELETED.value:
                # a deleted chat stays deleted; re-ingest must not resurrect it
                return existing

        from .pii import scan_and_maybe_redact
        found: list = []
        for m in conv.messages:
            text, types, red = scan_and_maybe_redact(
                str(m.get("content", "")), self.redact_pii)
            m["content"] = text
            m["pii_types"] = types
            m["redacted"] = red
            found.extend(types)
        conv.pii_types = sorted(set(found))
        conv.redacted = any(m.get("redacted") for m in conv.messages)
        if conv.pii_types and "pii" not in conv.flags:
            conv.flags = list(conv.flags) + ["pii"]

        # sensitivity of the chat = the most sensitive thing said in it
        from .classification import classify, LEVELS
        if not conv.classification:
            probe = MemoryUnit(content=conv.transcript()[:4000],
                               namespace=conv.namespace,
                               pii_types=conv.pii_types)
            conv.classification = classify(probe)

        # Zero-retention deployments keep the shape of the chat, not its words
        if self.zero_retention:
            conv.messages = [{"role": m.get("role", "?"),
                              "content": "[zero-retention: not persisted]",
                              "ts": m.get("ts", now_iso())}
                             for m in conv.messages]
            conv.redacted = True

        # company rules are checked against what was actually said
        if self.policy_guard is not None:
            probe = MemoryUnit(content=conv.transcript()[:4000],
                               namespace=conv.namespace)
            for v in self.policy_guard.evaluate(probe):
                tag = f"policy:{v.rule_id}"
                if tag not in conv.flags:
                    conv.flags = list(conv.flags) + [tag]

        conv.message_count = len(conv.messages)
        self._put_conv_row(conv)
        self._append_event(actor, action, conv)
        self.db.commit()
        self._fire_conv(action, conv)
        return conv

    def _fire_conv(self, action: str, c: Conversation):
        if self.event_hook is None:
            return
        try:
            self.event_hook(action, {"id": c.id, "subject": ",".join(c.subjects),
                                     "attribute": "conversation",
                                     "value": c.source_system,
                                     "content": c.title or c.transcript()[:200]})
        except Exception:
            pass

    def get_conversation(self, conv_id: str) -> Optional[Conversation]:
        row = self.db.execute("SELECT * FROM conversations WHERE id=?",
                              (conv_id,)).fetchone()
        return self._row_to_conv(row) if row else None

    def conversation_by_external(self, external_id: str,
                                 source_system: Optional[str] = None):
        """Find a chat by the vendor's own id — how a fact points home."""
        sql = "SELECT * FROM conversations WHERE external_id=?"
        args = [external_id]
        if source_system:
            sql += " AND source_system=?"
            args.append(source_system)
        row = self.db.execute(sql, args).fetchone()
        return self._row_to_conv(row) if row else None

    def link_fact(self, conv_id: str, fact_id: str):
        """Record that a fact was extracted from this chat (both directions:
        the fact already carries conversation_id in its provenance)."""
        c = self.get_conversation(conv_id)
        if not c or fact_id in c.fact_ids:
            return
        c.fact_ids = list(c.fact_ids) + [fact_id]
        self._put_conv_row(c)
        self.db.commit()

    def facts_from_conversation(self, conv_id: str) -> list:
        """Every fact that came out of one chat."""
        c = self.get_conversation(conv_id)
        if not c:
            return []
        out = [self.get(fid) for fid in c.fact_ids]
        out = [m for m in out if m]
        if out:
            return out
        # fall back to provenance for chats ingested before linking
        keys = [k for k in (c.external_id, c.id) if k]
        found = []
        for m in self.all_memories():
            if (m.provenance or {}).get("conversation_id") in keys:
                found.append(m)
        return found

    def conversation_for_memory(self, memory_id: str) -> Optional[Conversation]:
        """Open the chat a fact came from — the other half of the trace."""
        m = self.get(memory_id)
        if not m:
            return None
        ext = (m.provenance or {}).get("conversation_id", "")
        if not ext:
            return None
        return (self.conversation_by_external(
            ext, (m.provenance or {}).get("source_system"))
            or self.conversation_by_external(ext) or self.get_conversation(ext))

    def search_conversations(self, query: str = "", agent: str = "admin",
                             employee: Optional[str] = None,
                             source_system: Optional[str] = None,
                             status: str = "active", limit: int = 50,
                             log: bool = True) -> list:
        """Search whole transcripts, behind the same ACL walls as facts."""
        allowed = self.policy.allowed_namespaces(agent)
        ids = None
        if query and self.have_fts:
            safe = " ".join(t for t in query.replace('"', " ").split())
            try:
                rows = self.db.execute(
                    "SELECT id FROM conv_fts WHERE conv_fts MATCH ? LIMIT 500",
                    (safe,)).fetchall()
                ids = [r["id"] for r in rows]
            except sqlite3.OperationalError:
                ids = None
        sql = "SELECT * FROM conversations WHERE 1=1"
        args: list = []
        if status and status != "all":
            sql += " AND status=?"; args.append(status)
        if employee:
            sql += " AND employee=?"; args.append(employee)
        if source_system:
            sql += " AND source_system=?"; args.append(source_system)
        if allowed is not None:
            sql += f" AND namespace IN ({','.join('?'*len(allowed))})"
            args.extend(allowed)
        if ids is not None:
            if not ids:
                return []
            sql += f" AND id IN ({','.join('?'*len(ids))})"
            args.extend(ids)
        sql += " ORDER BY started_at DESC LIMIT ?"
        args.append(limit)
        rows = self.db.execute(sql, args).fetchall()
        out = [self._row_to_conv(r) for r in rows]
        if log and out:
            self._log_retrieval(agent, query, [c.id for c in out], "conversation")
        return out

    def delete_conversation(self, conv_id: str, actor: str = "system"):
        """Erase a whole chat, with a receipt. Legal hold wins."""
        c = self.get_conversation(conv_id)
        if not c:
            return None
        if c.legal_hold:
            return {"blocked": True, "reason": "conversation is under legal hold",
                    "conversation_id": conv_id}
        c.status = MemoryStatus.DELETED.value
        c.messages = [{"role": m.get("role", "?"), "content": "[deleted]",
                       "ts": m.get("ts", now_iso())} for m in c.messages]
        self._put_conv_row(c)
        seq = self._append_event(actor, "conversation_deleted", c)
        receipt = self._issue_receipt("conversation_deletion", {
            "conversation_id": conv_id, "actor": actor, "event_seq": seq,
            "messages_erased": c.message_count})
        self.db.commit()
        return receipt

    def conversations_for_subject(self, subject: str) -> list:
        rows = self.db.execute(
            "SELECT * FROM conversations WHERE status!=?",
            (MemoryStatus.DELETED.value,)).fetchall()
        return [c for c in (self._row_to_conv(r) for r in rows)
                if subject in c.subjects]

    def expire_conversations(self, actor: str = "retention") -> int:
        """Retention: retire transcripts past their keep-until date."""
        now = now_iso()
        rows = self.db.execute(
            "SELECT * FROM conversations WHERE status=? AND expires_at IS NOT NULL"
            " AND expires_at < ?", (MemoryStatus.ACTIVE.value, now)).fetchall()
        n = 0
        for r in rows:
            c = self._row_to_conv(r)
            if c.legal_hold:
                continue                      # litigation freeze outranks retention
            c.status = MemoryStatus.EXPIRED.value
            self._put_conv_row(c)
            self._append_event(actor, "conversation_expired", c)
            n += 1
        self.db.commit()
        return n

    def conversation_counts(self) -> dict:
        rows = self.db.execute(
            "SELECT status, COUNT(*) n FROM conversations GROUP BY status")
        return {r["status"]: r["n"] for r in rows}

    # ---- who did what: per-employee accountability ----------------------
    def employee_activity(self, employee: Optional[str] = None) -> list:
        """What each person taught the AIs, and from which tools. Built from
        stored facts and conversations rather than a separate log, so it can't
        drift out of sync with reality."""
        people: dict = {}

        def bucket(name, email, dept):
            key = name or email or "unattributed"
            return people.setdefault(key, {
                "employee": key, "employee_email": email, "department": dept,
                "facts": 0, "conversations": 0, "messages": 0,
                "flagged": 0, "pii": 0, "held_for_review": 0,
                "sources": {}, "last_active": ""})

        for m in self.all_memories():
            if m.status == MemoryStatus.DELETED.value:
                continue
            p = (m.provenance or {})
            if employee and p.get("employee") != employee:
                continue
            b = bucket(p.get("employee", ""), p.get("employee_email", ""),
                       p.get("department", ""))
            b["facts"] += 1
            src = p.get("source_system", "unknown")
            b["sources"][src] = b["sources"].get(src, 0) + 1
            if any(str(f).startswith("policy") for f in (m.flags or [])):
                b["flagged"] += 1
            if m.pii_types:
                b["pii"] += 1
            if m.status == MemoryStatus.QUARANTINED.value:
                b["held_for_review"] += 1
            if m.occurred_at > b["last_active"]:
                b["last_active"] = m.occurred_at

        for r in self.db.execute("SELECT * FROM conversations WHERE status!=?",
                                 (MemoryStatus.DELETED.value,)):
            c = self._row_to_conv(r)
            if employee and c.employee != employee:
                continue
            b = bucket(c.employee, c.employee_email, c.department)
            b["conversations"] += 1
            b["messages"] += c.message_count
            b["sources"][c.source_system] = b["sources"].get(c.source_system, 0) + 1
            if any(str(f).startswith("policy") for f in (c.flags or [])):
                b["flagged"] += 1
            if c.pii_types:
                b["pii"] += 1
            if c.started_at > b["last_active"]:
                b["last_active"] = c.started_at

        return sorted(people.values(),
                      key=lambda p: (p["facts"] + p["conversations"]), reverse=True)

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
