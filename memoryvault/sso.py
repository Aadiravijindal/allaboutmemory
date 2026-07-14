"""Enterprise SSO via WorkOS (SAML / OIDC) — real login for enterprises.

Activates when WORKOS_API_KEY + WORKOS_CLIENT_ID are pasted. Provides the
hosted-auth redirect + callback that exchanges a code for a user profile,
then mints a MemoryVault session bound to the user's org and role.

Without WorkOS keys, the API keeps working on API-key auth (demo), so
nothing breaks offline. The session layer is real either way.
"""
from __future__ import annotations

import os
import secrets
import time
from typing import Optional

WORKOS_API_KEY = os.environ.get("WORKOS_API_KEY", "")
WORKOS_CLIENT_ID = os.environ.get("WORKOS_CLIENT_ID", "")
REDIRECT_URI = os.environ.get("WORKOS_REDIRECT_URI",
                              "http://localhost:8000/auth/callback")


class Sessions:
    """In-memory session store (swap for Redis in prod)."""

    def __init__(self):
        self._s: dict = {}

    def create(self, org: str, email: str, role: str = "operator") -> str:
        sid = secrets.token_urlsafe(32)
        self._s[sid] = {"org": org, "email": email, "role": role,
                        "created": time.time()}
        return sid

    def get(self, sid: Optional[str]) -> Optional[dict]:
        return self._s.get(sid) if sid else None

    def destroy(self, sid: str):
        self._s.pop(sid, None)


SESSIONS = Sessions()


def sso_enabled() -> bool:
    return bool(WORKOS_API_KEY and WORKOS_CLIENT_ID)


def authorization_url(state: str) -> str:
    """Where to send the user to log in (WorkOS hosted auth)."""
    try:
        import workos
        from workos import WorkOSClient
        client = WorkOSClient(api_key=WORKOS_API_KEY,
                              client_id=WORKOS_CLIENT_ID)
        return client.sso.get_authorization_url(
            provider="authkit", redirect_uri=REDIRECT_URI, state=state)
    except Exception:
        # graceful: fall back to a local dev login page
        return f"/auth/dev-login?state={state}"


def complete_login(code: str) -> dict:
    """Exchange the callback code for a profile, return {org,email,role}."""
    try:
        from workos import WorkOSClient
        client = WorkOSClient(api_key=WORKOS_API_KEY,
                              client_id=WORKOS_CLIENT_ID)
        profile = client.sso.get_profile_and_token(code).profile
        org = profile.organization_id or (profile.email.split("@")[-1])
        return {"org": org, "email": profile.email, "role": "operator"}
    except Exception as e:
        raise RuntimeError(f"SSO exchange failed: {e}")
