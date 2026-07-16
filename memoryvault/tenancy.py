"""Multi-tenancy + API-key auth + RBAC.

Every request is scoped to an org; each org gets its own isolated vault
(one DB per tenant here; one schema/database per tenant in production
Postgres). API keys carry a role. Admin actions are audited.

Production swaps the key store for a real IdP (WorkOS SSO / SAML / OIDC) and
per-tenant DB credentials — the `resolve()` contract stays identical.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Optional

from .store import Vault
from .policy import Policy

ROLES = {"owner", "admin", "operator", "reviewer", "readonly"}

# what each role may do (checked by the API layer)
ROLE_CAPS = {
    "owner":    {"read", "write", "delete", "approve", "admin", "connect"},
    "admin":    {"read", "write", "delete", "approve", "admin", "connect"},
    "operator": {"read", "write", "connect"},
    "reviewer": {"read", "approve"},
    "readonly": {"read"},
}


@dataclass
class ApiKey:
    key_hash: str
    org: str
    role: str
    name: str = ""
    created_at: float = field(default_factory=time.time)


class ControlPlane:
    """Manages orgs, API keys, and per-tenant vaults. This is 'our cloud'
    metadata — never the customer's memories, which live in their vault."""

    def __init__(self, data_dir: str = "data", policy_path: Optional[str] = None):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.keys_path = os.path.join(data_dir, "apikeys.json")
        self.audit_path = os.path.join(data_dir, "admin_audit.log")
        self.policy_path = policy_path
        self._vaults: dict = {}
        self._keys: dict = self._load_keys()

    # ---- key management --------------------------------------------------
    def _load_keys(self) -> dict:
        if os.path.exists(self.keys_path):
            with open(self.keys_path) as f:
                return {k: ApiKey(**v) for k, v in json.load(f).items()}
        return {}

    def _save_keys(self):
        with open(self.keys_path, "w") as f:
            json.dump({k: v.__dict__ for k, v in self._keys.items()}, f,
                      indent=2)

    @staticmethod
    def _hash(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()

    def create_org(self, org: str, owner_name: str = "owner") -> str:
        """Create an org + its owner API key. Returns the raw key (shown once)."""
        raw = f"mv_{org}_{secrets.token_urlsafe(24)}"
        kh = self._hash(raw)
        self._keys[kh] = ApiKey(key_hash=kh, org=org, role="owner",
                                name=owner_name)
        self._save_keys()
        self.vault_for(org)  # materialize the tenant vault
        self.audit(org, "system", "create_org", {"owner": owner_name})
        return raw

    def issue_key(self, org: str, role: str, name: str = "") -> str:
        if role not in ROLES:
            raise ValueError(f"bad role {role}")
        raw = f"mv_{org}_{secrets.token_urlsafe(24)}"
        kh = self._hash(raw)
        self._keys[kh] = ApiKey(key_hash=kh, org=org, role=role, name=name)
        self._save_keys()
        return raw

    def resolve(self, raw_key: Optional[str]) -> Optional[ApiKey]:
        if not raw_key:
            return None
        return self._keys.get(self._hash(raw_key))

    @staticmethod
    def can(role: str, cap: str) -> bool:
        return cap in ROLE_CAPS.get(role, set())

    # ---- per-tenant vault isolation -------------------------------------
    def vault_for(self, org: str) -> Vault:
        if org not in self._vaults:
            path = os.path.join(self.data_dir, f"tenant_{org}.db")
            policy = Policy.load(self.policy_path) if self.policy_path else Policy()
            from .policy_guard import PolicyGuard
            self._vaults[org] = Vault(
                path, policy=policy,
                encrypt=bool(os.environ.get("MV_ENCRYPT")),
                policy_guard=PolicyGuard(),           # company-rule flagging on
                redact_pii=bool(os.environ.get("MV_REDACT_PII")))
        return self._vaults[org]

    # ---- admin audit -----------------------------------------------------
    def audit(self, org: str, actor: str, action: str, detail: dict):
        rec = {"ts": time.time(), "org": org, "actor": actor,
               "action": action, "detail": detail}
        with open(self.audit_path, "a") as f:
            f.write(json.dumps(rec) + "\n")
