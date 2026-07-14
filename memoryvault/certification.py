"""Portable-✓ certification (year-2 standards land-grab).

Validates that a memory export conforms to the CMIF spec (docs/SPEC.md) and
issues a signed "Memory Portable ✓" badge. This is how the format becomes
THE standard: vendors run their export through this, get certified, and
customers demand the badge. The signature makes a badge verifiable.
"""
from __future__ import annotations

import hashlib
import json
import time

REQUIRED_FIELDS = ["id", "content", "type", "provenance"]
RECOMMENDED = ["subject", "attribute", "value", "trust", "decay_class",
               "occurred_at"]
VALID_TYPES = {"fact", "preference", "episode", "procedure", "opinion"}


def validate_export(memories: list) -> dict:
    """Score an export against CMIF. Returns pass/fail + a compliance grade."""
    n = len(memories) or 1
    missing_required, missing_prov, missing_recommended, bad_type = 0, 0, 0, 0
    for m in memories:
        if not all(m.get(f) not in (None, "") for f in REQUIRED_FIELDS):
            missing_required += 1
        prov = m.get("provenance") or {}
        if not prov.get("source_system"):
            missing_prov += 1
        if m.get("type") not in VALID_TYPES:
            bad_type += 1
        if sum(1 for f in RECOMMENDED if m.get(f) in (None, "")) > 3:
            missing_recommended += 1
    required_ok = 1 - missing_required / n
    prov_ok = 1 - missing_prov / n
    rec_ok = 1 - missing_recommended / n
    score = round(100 * (0.5 * required_ok + 0.3 * prov_ok + 0.2 * rec_ok))
    passed = missing_required == 0 and missing_prov == 0
    grade = ("A" if score >= 95 else "B" if score >= 85 else
             "C" if score >= 70 else "F")
    return {"passed": passed, "score": score, "grade": grade,
            "checked": len(memories),
            "issues": {"missing_required_fields": missing_required,
                       "missing_provenance": missing_prov,
                       "invalid_type": bad_type,
                       "sparse_records": missing_recommended}}


def issue_badge(vendor: str, memories: list) -> dict:
    """Issue a signed Portable-✓ badge if the export passes."""
    result = validate_export(memories)
    badge = {"badge": "Memory Portable ✓" if result["passed"] else "Not certified",
             "vendor": vendor, "cmif_version": "0.1",
             "grade": result["grade"], "score": result["score"],
             "checked": result["checked"], "issued_at": time.time(),
             "detail": result["issues"]}
    body = json.dumps(badge, sort_keys=True)
    badge["signature"] = hashlib.sha256(body.encode()).hexdigest()
    return badge


def verify_badge(badge: dict) -> bool:
    b = dict(badge)
    sig = b.pop("signature", "")
    return hashlib.sha256(json.dumps(b, sort_keys=True).encode()).hexdigest() == sig
