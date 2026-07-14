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


class AwsKmsKeyProvider(KeyProvider):  # pragma: no cover - needs AWS
    """Production: the data key is wrapped by a CMK in the CUSTOMER's AWS
    KMS. We call Decrypt with their key; the plaintext data key lives only
    in memory in their tenant. This is the "we can't read your data"
    promise as infrastructure — the CMK never leaves the customer account.

    Env: MV_KMS_KEY_ID (customer CMK arn), MV_WRAPPED_KEY (b64 ciphertext).
    """

    def __init__(self, key_id: str = "", wrapped_key_b64: str = ""):
        self.key_id = key_id or os.environ.get("MV_KMS_KEY_ID", "")
        self.wrapped = wrapped_key_b64 or os.environ.get("MV_WRAPPED_KEY", "")
        import base64
        import boto3
        self._b64 = base64
        self._kms = boto3.client("kms")

    def get_key(self) -> bytes:
        if not self.wrapped:
            # first run: generate a data key under the customer CMK
            resp = self._kms.generate_data_key(KeyId=self.key_id,
                                                KeySpec="AES_256")
            # caller persists resp['CiphertextBlob'] as MV_WRAPPED_KEY
            import base64
            return base64.urlsafe_b64encode(resp["Plaintext"][:32])
        blob = self._b64.b64decode(self.wrapped)
        resp = self._kms.decrypt(CiphertextBlob=blob, KeyId=self.key_id)
        return self._b64.urlsafe_b64encode(resp["Plaintext"][:32])


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
