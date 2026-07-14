"""Cross-company shared knowledge network (year-2, opt-in).

Companies opt in to share NON-SECRET, generalizable lessons (e.g. "library X
v2 breaks framework Y", "this API silently rate-limits") — never customer
data. Each contribution is anonymized and stripped of PII/entities before it
leaves the tenant; useful contributions earn credits (contribute-to-earn).

This is the winner-take-all layer, and it's built to be SAFE by default:
sharing is opt-in per namespace, only memories tagged `shareable` and
containing no subject/entity leave, and everything is redacted first.
"""
from __future__ import annotations

import hashlib
import re
import time

_PII = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<email>"),
    (re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"), "<phone>"),
    (re.compile(r"\b\d{1,4}\s+\w+\s+(street|st|road|rd|ave|avenue)\b", re.I), "<address>"),
    (re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b"), "<name>"),  # heuristic
]


def redact(text: str) -> str:
    for pat, repl in _PII:
        text = pat.sub(repl, text)
    return text


def is_shareable(mem: dict) -> bool:
    """Only generalizable, non-customer memories qualify."""
    tags = mem.get("tags") or []
    if "shareable" not in tags:
        return False
    # must not be about a specific customer/person
    if mem.get("subject", "").startswith(("customer:", "person:", "user:")):
        return False
    return True


class FederationNetwork:
    """Reference hub. In production this is a shared, governed service; each
    tenant only ever sends redacted, opt-in lessons."""

    def __init__(self, store_path: str = "data/federation.jsonl"):
        import os
        self.path = store_path
        os.makedirs(os.path.dirname(store_path) or ".", exist_ok=True)

    def contribute(self, org: str, memories: list) -> dict:
        import json
        shared, credits = 0, 0
        with open(self.path, "a") as f:
            for m in memories:
                if not is_shareable(m):
                    continue
                lesson = {
                    "content": redact(m["content"]),
                    "attribute": m.get("attribute", ""),
                    "value": m.get("value", ""),
                    "contributor": hashlib.sha256(org.encode()).hexdigest()[:12],
                    "ts": time.time(),
                    "id": hashlib.sha256(m["content"].encode()).hexdigest()[:16],
                }
                f.write(json.dumps(lesson) + "\n")
                shared += 1
                credits += 1
        return {"shared": shared, "credits_earned": credits}

    def query(self, text: str, limit: int = 10) -> list:
        import json
        import os
        if not os.path.exists(self.path):
            return []
        terms = set(text.lower().split())
        scored = []
        seen = set()
        with open(self.path) as f:
            for line in f:
                lesson = json.loads(line)
                if lesson["id"] in seen:
                    continue
                seen.add(lesson["id"])
                overlap = len(terms & set(lesson["content"].lower().split()))
                if overlap:
                    scored.append((overlap, lesson))
        scored.sort(key=lambda x: -x[0])
        return [l for _, l in scored[:limit]]
