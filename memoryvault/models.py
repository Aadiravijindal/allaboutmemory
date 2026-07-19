"""Model router + deprecation notices.

Tracks which model wrote/used each memory, lets an org pin an allowed model
set, and surfaces deprecation notices so a model never changes silently
under the customer (a contract-level buyer demand).
"""
from __future__ import annotations

import time

# A small registry; in production this syncs from provider APIs.
MODEL_REGISTRY = {
    "claude-opus-4-8": {"provider": "anthropic", "status": "current"},
    "claude-sonnet-5": {"provider": "anthropic", "status": "current"},
    "gpt-4o": {"provider": "openai", "status": "current"},
    "gpt-4o-mini": {"provider": "openai", "status": "current"},
    "text-embedding-3-small": {"provider": "openai", "status": "current"},
    "gpt-4-turbo": {"provider": "openai", "status": "deprecated",
                    "retires": "2026-12-01"},
}


class ModelRouter:
    def __init__(self, allowed: list = None):
        # org's approved model set; empty = allow all current
        self.allowed = allowed or list(MODEL_REGISTRY.keys())

    def is_allowed(self, model: str) -> bool:
        return model in self.allowed

    def deprecation_notices(self) -> list:
        out = []
        for m in self.allowed:
            info = MODEL_REGISTRY.get(m, {})
            if info.get("status") == "deprecated":
                out.append({"model": m, "provider": info.get("provider"),
                            "retires": info.get("retires"),
                            "message": f"{m} is deprecated and retires "
                                       f"{info.get('retires')}. Migrate before then."})
        return out

    def status(self) -> dict:
        return {"allowed": self.allowed,
                "registry": MODEL_REGISTRY,
                "deprecations": self.deprecation_notices(),
                "checked_at": time.time()}
