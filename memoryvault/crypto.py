"""Feature 1.4 — Locked with the customer's own keys.

Envelope-encryption interface. In production the KeyProvider wraps the
customer's cloud KMS (AWS KMS / Azure Key Vault / GCP KMS) so keys never
leave their account. For local/dev use, a key file on disk stands in.

If the `cryptography` package is unavailable, the vault runs unencrypted
and says so loudly — never silently.
"""
from __future__ import annotations

import os
import sys

try:
    from cryptography.fernet import Fernet
    HAVE_CRYPTO = True
except Exception:  # pragma: no cover
    HAVE_CRYPTO = False


class KeyProvider:
    """Interface: production implementations call the customer's KMS."""

    def get_key(self) -> bytes:
        raise NotImplementedError


class LocalKeyProvider(KeyProvider):
    """Dev/demo: key file next to the vault. Replace with KMS in prod."""

    def __init__(self, key_path: str):
        self.key_path = key_path

    def get_key(self) -> bytes:
        if os.path.exists(self.key_path):
            with open(self.key_path, "rb") as f:
                return f.read().strip()
        key = Fernet.generate_key()
        with open(self.key_path, "wb") as f:
            f.write(key)
        os.chmod(self.key_path, 0o600)
        return key


class Cipher:
    def __init__(self, provider: KeyProvider | None):
        self.enabled = HAVE_CRYPTO and provider is not None
        self._fernet = Fernet(provider.get_key()) if self.enabled else None
        if provider is not None and not HAVE_CRYPTO:
            print(
                "[memoryvault] WARNING: 'cryptography' not installed — "
                "vault content is NOT encrypted at rest.",
                file=sys.stderr,
            )

    def encrypt(self, text: str) -> str:
        if not self.enabled:
            return text
        return "enc:" + self._fernet.encrypt(text.encode("utf-8")).decode("ascii")

    def decrypt(self, text: str) -> str:
        if not text.startswith("enc:"):
            return text
        if not self.enabled:
            raise RuntimeError("Encrypted content but no key available.")
        return self._fernet.decrypt(text[4:].encode("ascii")).decode("utf-8")
