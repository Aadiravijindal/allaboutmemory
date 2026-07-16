"""Enterprise governance controls: legal hold, kill switch, SIEM export,
anomaly (poison) detection, and compliance reporting.

These sit on top of the vault and its event log — small, sharp controls
that security/compliance teams gate purchasing on.
"""
from __future__ import annotations

import json
import os
import time
from collections import Counter
from datetime import datetime, timezone

from .schema import MemoryStatus


# --------------------------------------------------------------- Kill switch
class KillSwitch:
    """Emergency freeze. Flip it (globally or per source) and no new memory
    is accepted until released — the 'stop everything now' control."""

    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, "killswitch.json")
        os.makedirs(data_dir, exist_ok=True)

    def _load(self) -> dict:
        if os.path.exists(self.path):
            with open(self.path) as f:
                return json.load(f)
        return {"global": False, "sources": []}

    def _save(self, d):
        with open(self.path, "w") as f:
            json.dump(d, f)

    def freeze(self, source: str = None):
        d = self._load()
        if source:
            d["sources"] = sorted(set(d["sources"] + [source]))
        else:
            d["global"] = True
        self._save(d)

    def release(self, source: str = None):
        d = self._load()
        if source:
            d["sources"] = [s for s in d["sources"] if s != source]
        else:
            d["global"] = False
        self._save(d)

    def blocked(self, source: str = None) -> bool:
        d = self._load()
        return d["global"] or (source in d["sources"] if source else False)

    def status(self) -> dict:
        return self._load()


# --------------------------------------------------------------- Legal hold
def apply_legal_hold(vault, subject: str, actor: str, on: bool = True) -> dict:
    """Freeze (or release) every memory about a subject so it cannot be
    deleted or expired during litigation. Logged for the audit trail."""
    held = 0
    for m in vault.all_memories():
        if m.subject == subject and m.status != MemoryStatus.DELETED.value:
            m.legal_hold = on
            vault._put_row(m)
            vault._append_event(actor, "legal_hold_on" if on else "legal_hold_off", m)
            held += 1
    vault.db.commit()
    return {"subject": subject, "held": held, "on": on}


# --------------------------------------------------------------- SIEM export
def siem_export(vault, since_seq: int = 0, fmt: str = "cef") -> list:
    """Stream audit events out to a SIEM (Splunk/Sentinel). Returns events
    since a cursor, in CEF-like or JSON form. In production this is pushed
    to an HTTPS collector / syslog endpoint on a schedule."""
    events = vault.events_since(since_seq)
    out = []
    for e in events:
        if fmt == "json":
            out.append(e)
        else:  # CEF-ish line for SIEM ingestion
            out.append(
                f"CEF:0|MemoryVault|vault|0.4|{e['action']}|memory {e['action']}|"
                f"3|rt={e['ts']} suser={e['actor']} externalId={e['memory_id']} "
                f"seq={e['seq']}")
    return out


# ------------------------------------------------- Anomaly / poison detection
def detect_anomalies(vault, window: int = 500) -> list:
    """Post-hoc scan for poisoning / abuse patterns over the event log:
    bursts of writes from one untrusted source, repeated identical injected
    content, or a source suddenly writing far above its baseline. Surfaces
    the cross-session attack pattern OWASP ASI06 warns about."""
    rows = vault.db.execute(
        "SELECT * FROM events ORDER BY seq DESC LIMIT ?", (window,)).fetchall()
    alerts = []
    by_actor = Counter()
    contents = Counter()
    for r in rows:
        by_actor[r["actor"]] += 1
        try:
            snap = json.loads(r["snapshot"])
            ch = (snap.get("provenance") or {}).get("channel", "")
            if ch in ("email", "web", "upload"):
                contents[snap.get("content", "")[:80]] += 1
        except Exception:
            pass
    # repeated identical untrusted content = likely injection attempt
    for content, n in contents.items():
        if n >= 3 and content:
            alerts.append({"type": "repeated_untrusted_write", "count": n,
                           "sample": content,
                           "detail": "same content injected repeatedly from an "
                                     "untrusted channel"})
    # a single actor dominating recent writes = possible runaway/poison source
    if by_actor:
        top, cnt = by_actor.most_common(1)[0]
        if cnt > window * 0.6 and "rescue" not in top:
            alerts.append({"type": "write_burst", "actor": top, "count": cnt,
                           "detail": "one source is writing far above baseline"})
    return alerts


# --------------------------------------------------------- Compliance report
def compliance_report(vault, killswitch, org: str) -> dict:
    """One-click evidence pack for an EU AI Act / SOC 2 / GDPR review:
    counts, integrity, retention posture, holds, flags, and the controls in
    force. This is the paper an auditor asks for."""
    mems = vault.all_memories()
    flagged = [m for m in mems if getattr(m, "flags", [])]
    on_hold = [m for m in mems if getattr(m, "legal_hold", False)]
    pii = [m for m in mems if getattr(m, "pii_types", [])]
    receipts = vault.receipts_list()
    return {
        "report": "MemoryVault Compliance Evidence",
        "org": org,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": vault.counts(),
        "integrity": {"event_chain_intact": vault.verify_chain(),
                      "total_events": vault.last_seq()},
        "governance": {
            "memories_flagged": len(flagged),
            "memories_on_legal_hold": len(on_hold),
            "memories_with_pii": len(pii),
            "deletion_receipts": len(receipts),
            "kill_switch": killswitch.status(),
        },
        "controls_in_force": [
            "Provenance + employee attribution on every memory",
            "RBAC + namespace access walls",
            "Immutable hash-chained audit log",
            "Approval Room (memory-poisoning defense, OWASP ASI06)",
            "Policy Guard (company-rule violation flagging)",
            "PII detection & redaction",
            "Legal hold, retention/expiry, delete-with-receipt",
            "Anomaly detection + SIEM export",
        ],
        "eu_ai_act": {
            "record_keeping_article_12": "event log retained, exportable",
            "human_oversight": "approval queue + kill switch",
            "traceability": "every AI decision links to the memories used "
                            "(flight recorder)",
        },
    }
