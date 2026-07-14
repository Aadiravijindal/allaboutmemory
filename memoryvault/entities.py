"""Entity resolution — "Acme" == "Acme Corp" == "ACME Corporation".

Contradiction detection and dedupe both need to know when two memories are
about the *same* thing. The demo compared subjects/attributes as exact
strings; this normalizes them so real-world variation collapses correctly.

Production swaps `canonical()` for a proper entity-resolution service (a
learned linker over the customer's CRM/identity graph), but the interface —
"give me the canonical id for this surface form" — stays the same.
"""
from __future__ import annotations

import re

_SUFFIXES = {"corp", "corporation", "inc", "incorporated", "ltd", "limited",
             "llc", "co", "company", "plc", "gmbh", "sa", "ag", "the"}
_PUNCT = re.compile(r"[^a-z0-9\s]")
_WS = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Fold surface variants of an org/person name to a canonical token."""
    s = _PUNCT.sub(" ", name.lower())
    s = _WS.sub(" ", s).strip()
    words = [w for w in s.split() if w not in _SUFFIXES]
    return " ".join(words) if words else s


def canonical_subject(subject: str) -> str:
    """Canonicalize a 'type:name' subject key (e.g. 'customer:Acme Corp')."""
    if ":" in subject:
        kind, name = subject.split(":", 1)
        return f"{kind.strip().lower()}:{normalize_name(name)}"
    return normalize_name(subject)


def canonical_attribute(attribute: str) -> str:
    return _WS.sub("_", attribute.strip().lower())


# Attributes whose truth is set-at-a-point vs evolves-over-time.
# Used by per-attribute conflict policy (Feature 3.2, upgraded).
ATTRIBUTE_POLICY = {
    # attribute -> "recency" (newer wins) or "trust" (trusted source wins)
    "plan": "recency",
    "address": "recency",
    "status": "recency",
    "mood": "recency",
    "renewal_risk": "recency",
    "invoice_account": "trust",     # money routing: trust the verified source
    "primary_contact": "recency",
    "ssn": "trust",
    "dob": "trust",
    "legal_name": "trust",
}


def conflict_strategy(attribute: str) -> str:
    return ATTRIBUTE_POLICY.get(canonical_attribute(attribute), "recency")
