"""Canonical memory schema — the format every memory travels in.

This is the interchange format of the whole product: every connector
translates INTO this, the vault stores it, every projection translates
OUT of it. (Feature 1.2: every memory carries its "papers".)
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_date(value: str) -> str:
    """Resolve relative date tokens so demo fixtures never rot over time.
    '-2d'/'-3h' -> that long before now; anything else returned unchanged.
    """
    if isinstance(value, str) and value.startswith("-") and value[-1] in "dh":
        try:
            n = int(value[1:-1])
            delta = timedelta(days=n) if value[-1] == "d" else timedelta(hours=n)
            return (datetime.now(timezone.utc) - delta).isoformat()
        except ValueError:
            return value
    return value or now_iso()


class MemoryType(str, Enum):
    FACT = "fact"              # verifiable statement: "customer plan = Pro"
    PREFERENCE = "preference"  # "prefers evening calls"
    EPISODE = "episode"        # something that happened: "call on March 3"
    PROCEDURE = "procedure"    # learned how-to: "escalate via form X"
    OPINION = "opinion"        # subjective — flagged by the yes-man filter


class MemoryStatus(str, Enum):
    ACTIVE = "active"
    QUARANTINED = "quarantined"  # waiting in the Approval Room (5.4)
    SUPERSEDED = "superseded"    # lost a contradiction fight (3.2 / 7.3)
    EXPIRED = "expired"          # retired by the Freshness Keeper (7.2)
    DELETED = "deleted"          # tombstone kept for the receipt (6.3)


class DecayClass(str, Enum):
    """How fast a fact ages (Feature 7.2)."""
    PERMANENT = "permanent"  # names, birthdays — never expires
    SLOW = "slow"            # job titles, tech stack — ~1 year
    MEDIUM = "medium"        # plans, pricing, projects — ~90 days
    FAST = "fast"            # moods, statuses — ~7 days


DECAY_TTL_DAYS = {
    DecayClass.PERMANENT: None,
    DecayClass.SLOW: 365,
    DecayClass.MEDIUM: 90,
    DecayClass.FAST: 7,
}

# Channels the Rulebook treats as untrusted by default (Feature 5.4).
# These are third-party ingestion paths (the memory-poisoning vectors).
# First-party writes (manual, MCP, CRM) are gated by trust score instead.
UNTRUSTED_CHANNELS = {"email", "web", "upload", "external_doc"}


@dataclass
class Provenance:
    """The memory's ID card: where it came from (Feature 1.2), now with
    full enterprise attribution — which employee, which account, which
    conversation, from which AI, when."""
    source_system: str = "manual"   # e.g. "salesforce_agentforce", "chatgpt"
    agent_id: str = "unknown"       # which agent wrote it
    channel: str = "unknown"        # "call", "chat", "email", "web", "upload"
    author: str = ""                # human/system behind it, if known
    employee: str = ""              # the employee/user account responsible
    employee_email: str = ""        # their email (for audit/attribution)
    department: str = ""            # e.g. "sales", "support"
    conversation_id: str = ""       # which chat/session it came from
    ip: str = ""                    # origin IP, if captured
    occurred_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MemoryUnit:
    """One memory, with everything the product needs to trust it."""
    content: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    type: str = MemoryType.FACT.value
    namespace: str = "general"      # ACL wall (Feature 6.1): "sales", "hr"...
    subject: str = ""               # who/what it is about: "customer:acme"
    attribute: str = ""             # canonical key for conflict detection: "plan"
    value: str = ""                 # canonical value: "Pro"
    entities: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    trust: float = 0.5              # 0..1, from source scoring
    status: str = MemoryStatus.ACTIVE.value
    decay_class: str = DecayClass.MEDIUM.value
    occurred_at: str = field(default_factory=now_iso)
    ingested_at: str = field(default_factory=now_iso)
    expires_at: Optional[str] = None
    provenance: dict = field(default_factory=lambda: Provenance().to_dict())
    version: int = 1
    supersedes: Optional[str] = None
    bias_risk: bool = False         # set by the yes-man filter (7.4)
    # ---- enterprise governance fields ----
    tier: str = "team"              # personal | team | company (memory tiers)
    flags: list = field(default_factory=list)   # policy/PII/security flags
    legal_hold: bool = False        # frozen for litigation — cannot be deleted
    pii_types: list = field(default_factory=list)  # detected PII categories
    redacted: bool = False          # whether content was PII-redacted
    classification: str = ""        # public|internal|confidential|restricted

    def __post_init__(self):
        if self.expires_at is None:
            self.expires_at = self.compute_expiry()

    def compute_expiry(self) -> Optional[str]:
        ttl = DECAY_TTL_DAYS.get(DecayClass(self.decay_class))
        if ttl is None:
            return None
        base = datetime.fromisoformat(self.occurred_at)
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        return (base + timedelta(days=ttl)).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryUnit":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def from_json(cls, s: str) -> "MemoryUnit":
        return cls.from_dict(json.loads(s))


def conflict_key(m: MemoryUnit) -> Optional[tuple]:
    """Two memories 'fight' when they claim different values for the same
    subject+attribute — compared on CANONICAL forms so 'Acme' and
    'Acme Corp' collapse to one entity (Features 3.2 and 7.3)."""
    if m.subject and m.attribute:
        # imported lazily to avoid a cycle at module load
        from .entities import canonical_subject, canonical_attribute
        return (canonical_subject(m.subject), canonical_attribute(m.attribute))
    return None
