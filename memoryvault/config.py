"""The single place you paste keys.

Reads a `.env` file (or real environment variables) and exposes typed
config. Everything else — connectors, billing, encryption, Postgres,
embeddings — activates automatically based on which keys are present.
Paste a key, restart, that integration is live. Paste nothing, the demo
runs on safe local defaults.

    cp .env.example .env    # then paste your keys
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass


def _strip_inline_comment(v: str) -> str:
    """Remove a trailing ' # comment' from a value. A value that is only a
    comment (or blank) resolves to empty."""
    v = v.strip()
    if v.startswith("#"):
        return ""
    return re.split(r"\s+#", v, 1)[0].strip()


def _load_dotenv(path: str = ".env"):
    """Minimal .env loader (no dependency). Real env vars win over file."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = _strip_inline_comment(v.strip()).strip('"').strip("'")
            os.environ.setdefault(k.strip(), v)


_load_dotenv(os.environ.get("MV_ENV_FILE", ".env"))


def _b(name: str, default=False) -> bool:
    v = _strip_inline_comment(os.environ.get(name, str(default)))
    return v.lower() in ("1", "true", "yes")


def _int(name: str, default: int) -> int:
    """Defensive int env read — tolerates stray comments/whitespace."""
    raw = _strip_inline_comment(os.environ.get(name, str(default)))
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


@dataclass
class Config:
    # ---- storage -------------------------------------------------------
    database_url: str = os.environ.get("DATABASE_URL", "")          # empty => SQLite
    data_dir: str = os.environ.get("MV_DATA", "data")

    # ---- encryption (customer KMS) -------------------------------------
    encrypt: bool = _b("MV_ENCRYPT")
    kms_key_id: str = os.environ.get("MV_KMS_KEY_ID", "")
    kms_provider: str = os.environ.get("MV_KMS_PROVIDER", "local")   # local|aws

    # ---- embeddings ----------------------------------------------------
    embeddings: str = os.environ.get("MV_EMBEDDINGS", "local")       # local|openai
    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")

    # ---- connector credentials (paste to activate) ---------------------
    salesforce_token: str = os.environ.get("SALESFORCE_TOKEN", "")
    salesforce_instance: str = os.environ.get("SALESFORCE_INSTANCE_URL", "")
    ms_graph_token: str = os.environ.get("MS_GRAPH_TOKEN", "")
    intercom_token: str = os.environ.get("INTERCOM_TOKEN", "")
    mem0_api_key: str = os.environ.get("MEM0_API_KEY", "")
    zep_api_key: str = os.environ.get("ZEP_API_KEY", "")
    zep_base_url: str = os.environ.get("ZEP_BASE_URL", "https://api.getzep.com")
    openai_export_file: str = os.environ.get("OPENAI_EXPORT_FILE", "")

    # ---- billing -------------------------------------------------------
    stripe_secret_key: str = os.environ.get("STRIPE_SECRET_KEY", "")
    stripe_webhook_secret: str = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    stripe_price_platform: str = os.environ.get("STRIPE_PRICE_PLATFORM", "")
    stripe_price_per_connector: str = os.environ.get("STRIPE_PRICE_CONNECTOR", "")

    # ---- SSO (WorkOS) --------------------------------------------------
    workos_api_key: str = os.environ.get("WORKOS_API_KEY", "")
    workos_client_id: str = os.environ.get("WORKOS_CLIENT_ID", "")

    # ---- evidence locker + sovereign + temporal ------------------------
    locker_bucket: str = os.environ.get("MV_LOCKER_BUCKET", "")
    sovereign: str = os.environ.get("MV_SOVEREIGN", "us")
    temporal_host: str = os.environ.get("MV_TEMPORAL_HOST", "")

    # ---- runtime -------------------------------------------------------
    sync_interval_seconds: int = _int("MV_SYNC_INTERVAL", 3600)

    def activated(self) -> dict:
        """What's live vs demo — powers the `setup` status screen."""
        return {
            "storage": "postgres" if self.database_url else "sqlite (demo)",
            "encryption": (f"{self.kms_provider} KMS" if self.encrypt
                           else "off (demo)"),
            "embeddings": self.embeddings,
            "connectors_live": [name for name, on in {
                "salesforce": bool(self.salesforce_token),
                "microsoft_copilot": bool(self.ms_graph_token),
                "intercom": bool(self.intercom_token),
                "mem0": bool(self.mem0_api_key),
                "zep": bool(self.zep_api_key),
                "chatgpt_export": bool(self.openai_export_file),
            }.items() if on],
            "billing": "stripe" if self.stripe_secret_key else "off (demo)",
        }


CONFIG = Config()
