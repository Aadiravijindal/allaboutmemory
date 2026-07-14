"""PART 6 — THE RULEBOOK. Set rules once, enforced everywhere.

Policies are plain YAML (see policies/default.yaml). Enforcement happens
at exactly two chokepoints — every write and every read goes through
here — so there are no bypasses.

  6.1 Who-sees-what walls   -> allowed_namespaces() filters every read
  6.2 Auto-expiry rules     -> ttl_overrides feed the Freshness Keeper
  5.4 The approval room     -> evaluate_write() quarantines sketchy sources
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

try:
    import yaml
    HAVE_YAML = True
except Exception:  # pragma: no cover
    HAVE_YAML = False

from .schema import MemoryUnit, MemoryStatus, UNTRUSTED_CHANNELS

DEFAULT_POLICY = {
    "quarantine": {
        # memories from these channels wait in the Approval Room
        "untrusted_channels": sorted(UNTRUSTED_CHANNELS),
        # anything below this trust score waits too
        "min_trust": 0.3,
    },
    "acl": {
        # agent/role -> namespaces it may read. "*" = everything.
        "default": ["general"],
        "admin": ["*"],
    },
    "ttl_overrides": {
        # tag or type -> ttl days (overrides decay class)
        "financial": 90,
        "pii": 365,
    },
    "projections": {
        # per-target diet (Feature 3.3); sync engine consults this
        "default": {"namespaces": ["general"], "min_trust": 0.3,
                    "exclude_bias_risk": True},
    },
}


@dataclass
class Policy:
    raw: dict = field(default_factory=lambda: dict(DEFAULT_POLICY))

    @classmethod
    def load(cls, path: Optional[str] = None) -> "Policy":
        if path and HAVE_YAML:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            merged = dict(DEFAULT_POLICY)
            for k, v in data.items():
                if isinstance(v, dict) and isinstance(merged.get(k), dict):
                    merged[k] = {**merged[k], **v}
                else:
                    merged[k] = v
            return cls(raw=merged)
        return cls()

    # ---- Feature 5.4: the Approval Room decision -------------------------
    def evaluate_write(self, m: MemoryUnit) -> str:
        q = self.raw.get("quarantine", {})
        channel = (m.provenance or {}).get("channel", "unknown")
        if channel in set(q.get("untrusted_channels", [])):
            return MemoryStatus.QUARANTINED.value
        if m.trust < float(q.get("min_trust", 0.0)):
            return MemoryStatus.QUARANTINED.value
        return MemoryStatus.ACTIVE.value

    # ---- Feature 6.1: who-sees-what walls --------------------------------
    def allowed_namespaces(self, agent: str) -> Optional[list]:
        """Returns None for unrestricted ('*'), else the allowed list."""
        acl = self.raw.get("acl", {})
        allowed = acl.get(agent, acl.get("default", ["general"]))
        if "*" in allowed:
            return None
        return list(allowed)

    def can_read(self, agent: str, namespace: str) -> bool:
        allowed = self.allowed_namespaces(agent)
        return allowed is None or namespace in allowed

    # ---- Feature 6.2: auto-expiry knobs ----------------------------------
    def ttl_override_days(self, m: MemoryUnit) -> Optional[int]:
        overrides = self.raw.get("ttl_overrides", {})
        for tag in m.tags or []:
            if tag in overrides:
                return int(overrides[tag])
        if m.type in overrides:
            return int(overrides[m.type])
        return None

    # ---- Feature 3.3: per-target projection profiles ---------------------
    def projection(self, target: str) -> dict:
        projections = self.raw.get("projections", {})
        return projections.get(target, projections.get("default", {}))
