"""PII detection & redaction (enterprise feature).

Scans memory content for sensitive data before it is stored, tags the PII
types found, and (per policy) redacts it so raw sensitive data never lands
in the vault. Regulated industries (health, finance, legal) will not adopt
AI memory without this.

Detection is deterministic regex here (fast, offline, auditable). In
production this runs in-tenant and can be swapped for a trained NER model
via the same detect() interface — but the regex layer stays as a
guaranteed floor.
"""
from __future__ import annotations

import re
from typing import Tuple

# (label, pattern, redaction placeholder)
_PATTERNS = [
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[EMAIL]"),
    ("phone", re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"), "[PHONE]"),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    ("credit_card", re.compile(r"\b(?:\d[ -]*?){13,16}\b"), "[CARD]"),
    ("ip", re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"), "[IP]"),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"), "[IBAN]"),
    ("passport", re.compile(r"\b[A-Z]{1,2}\d{6,9}\b"), "[PASSPORT]"),
    ("dob", re.compile(r"\b(0?[1-9]|1[0-2])[/-](0?[1-9]|[12]\d|3[01])[/-](19|20)\d\d\b"), "[DOB]"),
]

# Credit-card regex is broad; validate with Luhn to cut false positives.
def _luhn_ok(number: str) -> bool:
    digits = [int(c) for c in re.sub(r"\D", "", number)]
    if len(digits) < 13:
        return False
    checksum, parity = 0, len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def detect(text: str) -> list:
    """Return the list of PII type labels found in the text."""
    found = []
    for label, pat, _ in _PATTERNS:
        for m in pat.finditer(text):
            if label == "credit_card" and not _luhn_ok(m.group()):
                continue
            found.append(label)
            break
    return sorted(set(found))


def redact(text: str) -> Tuple[str, list]:
    """Return (redacted_text, pii_types_found)."""
    found = []
    out = text
    for label, pat, placeholder in _PATTERNS:
        def _sub(m):
            if label == "credit_card" and not _luhn_ok(m.group()):
                return m.group()
            found.append(label)
            return placeholder
        out = pat.sub(_sub, out)
    return out, sorted(set(found))


def scan_and_maybe_redact(text: str, redact_enabled: bool) -> Tuple[str, list, bool]:
    """Return (content, pii_types, redacted?). If redact_enabled, sensitive
    spans are masked; otherwise content is left intact but still tagged."""
    types = detect(text)
    if types and redact_enabled:
        red, _ = redact(text)
        return red, types, True
    return text, types, False
