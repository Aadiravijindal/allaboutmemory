"""PART 2 — THE PLUGS. Connect every AI system.

Every connector implements one interface (Feature 2.3, two-way):
    extract() -> pull what an AI learned, as canonical MemoryUnits
    load()    -> deliver memories the AI should know
    watch()   -> return only what changed since a cursor (for daily sync)

Real production connectors talk to each vendor's actual API / export /
EU-Data-Act channel. Here we ship working reference connectors over local
fixtures so the whole pipeline runs end-to-end today, plus the registry
that makes "click to connect Salesforce" possible.

Source trust scores (Feature 1.2): a phone call is more trustworthy than
a scraped web page. This is where "papers" get their trust value.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from .schema import MemoryUnit, Provenance, MemoryType, DecayClass, now_iso

# Per-system default trust + channel (tunable per deployment).
SOURCE_PROFILE = {
    "salesforce_agentforce": {"trust": 0.8, "channel": "crm"},
    "microsoft_copilot":     {"trust": 0.75, "channel": "workplace"},
    "chatgpt_enterprise":    {"trust": 0.7, "channel": "chat"},
    "claude":                {"trust": 0.7, "channel": "chat"},
    "intercom_fin":          {"trust": 0.75, "channel": "support"},
    "mem0":                  {"trust": 0.7, "channel": "api"},
    "zep":                   {"trust": 0.7, "channel": "api"},
    "custom_mcp":            {"trust": 0.6, "channel": "api"},
    "email_ingest":          {"trust": 0.25, "channel": "email"},
    "web_ingest":            {"trust": 0.2, "channel": "web"},
}


class Connector:
    """Base plug. Subclass and implement the three verbs."""
    system = "generic"

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}

    def _profile(self) -> dict:
        return SOURCE_PROFILE.get(self.system, {"trust": 0.5,
                                                "channel": "unknown"})

    def _wrap(self, raw: dict) -> MemoryUnit:
        """Translate a raw vendor record INTO the canonical schema."""
        from .schema import resolve_date
        prof = self._profile()
        prov = Provenance(
            source_system=self.system,
            agent_id=raw.get("agent_id", self.system),
            channel=raw.get("channel", prof["channel"]),
            author=raw.get("author", ""),
            employee=raw.get("employee", ""),
            employee_email=raw.get("employee_email", ""),
            department=raw.get("department", ""),
            conversation_id=raw.get("conversation_id", ""),
            occurred_at=resolve_date(raw.get("occurred_at", now_iso())),
        )
        return MemoryUnit(
            content=raw["content"],
            type=raw.get("type", MemoryType.FACT.value),
            namespace=raw.get("namespace", "general"),
            subject=raw.get("subject", ""),
            attribute=raw.get("attribute", ""),
            value=raw.get("value", ""),
            entities=raw.get("entities", []),
            tags=raw.get("tags", []),
            trust=raw.get("trust", prof["trust"]),
            decay_class=raw.get("decay_class", DecayClass.MEDIUM.value),
            occurred_at=prov.occurred_at,
            provenance=prov.to_dict(),
        )

    def _wrap_conversation(self, raw: dict):
        """Translate a raw vendor chat INTO a canonical Conversation."""
        from .schema import Conversation, Message, resolve_date
        msgs = []
        for m in raw.get("messages", []):
            msgs.append(Message(
                role=m.get("role", "user"),
                content=str(m.get("content", "")),
                ts=resolve_date(m.get("ts", raw.get("started_at", now_iso()))),
                author=m.get("author", raw.get("employee", "")),
            ).to_dict())
        return Conversation(
            external_id=raw.get("id", raw.get("conversation_id", "")),
            source_system=self.system,
            title=raw.get("title", ""),
            messages=msgs,
            subjects=raw.get("subjects", []),
            namespace=raw.get("namespace", "general"),
            employee=raw.get("employee", ""),
            employee_email=raw.get("employee_email", ""),
            department=raw.get("department", ""),
            started_at=resolve_date(raw.get("started_at", now_iso())),
            retention_days=raw.get("retention_days"),
        )

    # -- override these ---------------------------------------------------
    def extract(self) -> list:
        raise NotImplementedError

    def extract_conversations(self) -> list:
        """Pull whole chats, not just the facts drawn from them. Optional:
        a source with no transcript API simply returns nothing."""
        return []

    def load(self, memories: list) -> dict:
        raise NotImplementedError

    def watch(self, since_token: str = "") -> tuple:
        """Return (memories, new_token). Default: full extract each time."""
        return self.extract(), now_iso()


class FileConnector(Connector):
    """Reference connector backed by a JSON fixture file.

    Simulates a vendor whose memory we pull out (extract) and push into
    (load). Every real connector — Salesforce, Copilot, ChatGPT, Claude —
    is this same shape with a vendor API behind extract/load instead of a
    file. That's the point: the hard part is the vendor plumbing, and the
    interface above it never changes.
    """

    def __init__(self, system: str, path: str, config: Optional[dict] = None):
        super().__init__(config)
        self.system = system
        self.path = path
        # deliveries go to a separate outbox so the pull-source stays pristine
        base, ext = os.path.splitext(path)
        self.outbox_path = base + ".outbox.json"
        # whole chats live alongside the facts, e.g. chatgpt.chats.json
        self.chats_path = base + ".chats.json"

    def _read(self) -> list:
        if not os.path.exists(self.path):
            return []
        with open(self.path) as f:
            return json.load(f)

    def _read_outbox(self) -> list:
        if not os.path.exists(self.outbox_path):
            return []
        with open(self.outbox_path) as f:
            return json.load(f)

    def _write_outbox(self, records: list):
        with open(self.outbox_path, "w") as f:
            json.dump(records, f, indent=2)

    def extract(self) -> list:
        return [self._wrap(r) for r in self._read()]

    def extract_conversations(self) -> list:
        if not os.path.exists(self.chats_path):
            return []
        with open(self.chats_path) as f:
            return [self._wrap_conversation(r) for r in json.load(f)]

    def load(self, memories: list) -> dict:
        """Deliver memories back into the vendor (Feature 2.3, delivery).
        Real platforms accept this via their knowledge/RAG channels
        (Graph connectors, Data Cloud, Projects, MCP resources). Here we
        write to an outbox file, keeping the pull-source fixture pristine."""
        records = self._read_outbox()
        have = {r.get("_mv_id") for r in records}
        added = 0
        for m in memories:
            if m.id in have:
                continue
            records.append({
                "_mv_id": m.id, "content": m.content, "subject": m.subject,
                "attribute": m.attribute, "value": m.value,
                "delivered_at": now_iso(),
            })
            added += 1
        self._write_outbox(records)
        return {"system": self.system, "delivered": added,
                "total": len(records)}

    def watch(self, since_token: str = "") -> tuple:
        mems = self.extract()
        fresh = [m for m in mems if m.provenance.get("occurred_at", "")
                 > since_token] if since_token else mems
        token = max((m.provenance.get("occurred_at", "") for m in mems),
                    default=since_token)
        return fresh, token


class ConnectorRegistry:
    """Powers 'click to connect X'. Maps a system name -> live connector."""

    def __init__(self):
        self._factories = {}
        self._live = {}

    def register(self, system: str, factory):
        self._factories[system] = factory

    def connect(self, system: str, **cfg) -> Connector:
        if system not in self._factories:
            raise KeyError(f"No connector registered for '{system}'. "
                           f"Available: {sorted(self._factories)}")
        conn = self._factories[system](**cfg)
        self._live[system] = conn
        return conn

    def live(self) -> dict:
        return dict(self._live)

    def available(self) -> list:
        return sorted(self._factories)


def default_registry(fixtures_dir: str) -> ConnectorRegistry:
    """Register reference connectors for the headline platforms."""
    reg = ConnectorRegistry()
    for system in ["salesforce_agentforce", "microsoft_copilot",
                   "chatgpt_enterprise", "claude", "intercom_fin",
                   "mem0", "zep", "custom_mcp", "email_ingest", "web_ingest"]:
        path = os.path.join(fixtures_dir, f"{system}.json")
        reg.register(system, (lambda s=system, p=path, **cfg:
                              FileConnector(s, p, cfg)))
    return reg
