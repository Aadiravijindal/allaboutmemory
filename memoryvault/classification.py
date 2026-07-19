"""Data classification + no-training guarantee (contract-level demands).

Auto-classifies every memory into a sensitivity level, and enforces the
"never train on our data / restrict routing" promise buyers put in
contracts. Classification drives handling: restricted memory can be
company-tier only, never federated, never sent to external model routing.
"""
from __future__ import annotations

import re

LEVELS = ["public", "internal", "confidential", "restricted"]

# signals that push a memory to a higher sensitivity level
_RESTRICTED = re.compile(r"\b(ssn|passport|medical|diagnos|salary|password|"
                         r"api[_ ]?key|secret|credit ?card|bank account)\b", re.I)
_CONFIDENTIAL = re.compile(r"\b(contract|pricing|revenue|acquisition|legal|"
                           r"nda|confidential|roadmap|termination)\b", re.I)


def classify(memory) -> str:
    """Return the sensitivity level for a memory."""
    text = (memory.content or "").lower()
    # PII already detected upstream bumps sensitivity
    if getattr(memory, "pii_types", None) or _RESTRICTED.search(text):
        return "restricted"
    if _CONFIDENTIAL.search(text) or "billing" in (memory.tags or []):
        return "confidential"
    if memory.namespace in ("hr", "finance", "legal"):
        return "confidential"
    if memory.namespace == "general" and not memory.subject:
        return "public"
    return "internal"


def training_allowed(memory, org_policy: dict) -> bool:
    """Whether this memory may be used for model training / external routing.
    Default is NO on the org (the contract guarantee); higher-sensitivity
    memory is never allowed regardless."""
    if not org_policy.get("allow_training", False):
        return False
    level = getattr(memory, "classification", None) or classify(memory)
    return level in ("public", "internal")


def routing_allowed(memory) -> bool:
    """Whether a memory may leave the tenant for external model routing.
    Restricted/confidential never leave."""
    level = getattr(memory, "classification", None) or classify(memory)
    return level in ("public", "internal")
