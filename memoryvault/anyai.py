"""Connect ANY AI — the universal doors.

A company doesn't just use Salesforce and ChatGPT. It uses a PDF-maker AI,
a transcription AI, a niche vertical tool — anything. Fixed connectors
can't cover "any AI", so this module provides three universal doors that
do, plus a per-org store so custom connections are added from the UI at
runtime (no code, no redeploy):

1. WEBHOOK INBOX — each org gets a unique ingest URL + secret token. Any
   tool that can send an HTTP POST (directly, or via Zapier/Make/n8n which
   bridge ~6000 apps) pushes what it learns. Records flow through the LLM
   transform + the Rulebook (trust/quarantine) like everything else.

2. UNIVERSAL REST CONNECTOR — point at any AI tool's API: base URL, auth
   header, where the records live in the response, and a field map. Saved
   per-org, then it behaves exactly like a built-in connector (rescue,
   watch, sync).

3. UNIVERSAL UPLOAD — every tool can export *something* (JSON/CSV). Drop
   the file in; the transform layer normalizes the mess into memories.

All three respect provenance: source name + channel are stamped on every
memory, so trust scoring and the Approval Room keep working.
"""
from __future__ import annotations

import csv
import io
import json
import os
import secrets
import time
from typing import Optional

from .schema import now_iso
from .connectors import Connector
from .http import get_json, HttpError
from .transform import get_transformer


# ---------------------------------------------------------------- REST door
class UniversalRestConnector(Connector):
    """Configurable plug for ANY AI tool with an HTTP API.

    config = {
      "base_url": "https://api.pdfai.example",
      "extract_path": "/v1/documents",         # GET endpoint listing records
      "auth_header": "Authorization",           # header name
      "auth_value": "Bearer sk-...",            # header value
      "records_path": "data",                   # where the list lives ("" = root)
      "field_map": {"content": "summary",       # canonical <- vendor field
                     "subject": "customer_id",
                     "occurred_at": "created"},
      "namespace": "general", "channel": "api", "trust": 0.6
    }
    """

    def __init__(self, name: str, config: dict):
        super().__init__(config)
        self.system = name
        self.c = config

    def _records(self, body):
        path = self.c.get("records_path", "")
        if not path:
            return body if isinstance(body, list) else [body]
        cur = body
        for part in path.split("."):
            cur = cur.get(part, []) if isinstance(cur, dict) else []
        return cur if isinstance(cur, list) else [cur]

    def extract(self) -> list:
        url = self.c["base_url"].rstrip("/") + self.c.get("extract_path", "/")
        headers = {}
        if self.c.get("auth_header") and self.c.get("auth_value"):
            headers[self.c["auth_header"]] = self.c["auth_value"]
        body = get_json(url, headers=headers)
        fmap = self.c.get("field_map", {})
        out = []
        for rec in self._records(body):
            raw = {canon: rec.get(src, "") for canon, src in fmap.items()} \
                if fmap else dict(rec)
            raw.setdefault("content", json.dumps(rec)[:500])
            raw.setdefault("namespace", self.c.get("namespace", "general"))
            raw.setdefault("channel", self.c.get("channel", "api"))
            raw.setdefault("trust", self.c.get("trust", 0.6))
            raw.setdefault("occurred_at", now_iso())
            out.append(self._wrap(raw))
        return out

    def load(self, memories: list) -> dict:
        # generic tools receive memory via their own ingestion if configured
        load_path = self.c.get("load_path", "")
        if not load_path:
            return {"system": self.system, "delivered": 0,
                    "note": "no load_path configured (extract-only)"}
        from .http import post_json
        headers = {}
        if self.c.get("auth_header") and self.c.get("auth_value"):
            headers[self.c["auth_header"]] = self.c["auth_value"]
        sent = 0
        for m in memories:
            try:
                post_json(self.c["base_url"].rstrip("/") + load_path,
                          headers=headers,
                          json={"content": m.content, "subject": m.subject,
                                "mv_id": m.id})
                sent += 1
            except HttpError:
                pass
        return {"system": self.system, "delivered": sent}


# ------------------------------------------------------- per-org custom store
class CustomConnectorStore:
    """Per-org registry of custom AI connections + the org's ingest token.
    Stored as JSON in the control-plane data dir; edited from the UI."""

    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, "custom_connectors.json")
        os.makedirs(data_dir, exist_ok=True)
        self._d = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.path):
            with open(self.path) as f:
                return json.load(f)
        return {}

    def _save(self):
        with open(self.path, "w") as f:
            json.dump(self._d, f, indent=2)

    def _org(self, org: str) -> dict:
        if org not in self._d:
            self._d[org] = {"connectors": {},
                            "ingest_token": "ing_" + secrets.token_urlsafe(24)}
            self._save()
        return self._d[org]

    def ingest_token(self, org: str) -> str:
        return self._org(org)["ingest_token"]

    def check_ingest_token(self, org: str, token: str) -> bool:
        return secrets.compare_digest(self._org(org)["ingest_token"],
                                      token or "")

    def add(self, org: str, name: str, kind: str, config: dict) -> dict:
        name = name.strip().lower().replace(" ", "_")
        entry = {"name": name, "kind": kind, "config": config,
                 "added_at": time.time()}
        self._org(org)["connectors"][name] = entry
        self._save()
        return entry

    def remove(self, org: str, name: str) -> bool:
        ok = self._org(org)["connectors"].pop(name, None) is not None
        self._save()
        return ok

    def list(self, org: str) -> list:
        # never leak auth values back out
        out = []
        for e in self._org(org)["connectors"].values():
            cfg = {k: ("•••" if "auth" in k or "token" in k or "key" in k
                       else v) for k, v in e["config"].items()}
            out.append({**e, "config": cfg})
        return out

    def build(self, org: str) -> list:
        """Instantiate live Connector objects for this org's REST customs."""
        conns = []
        for e in self._org(org)["connectors"].values():
            if e["kind"] == "rest":
                conns.append(UniversalRestConnector(e["name"], e["config"]))
        return conns


# ----------------------------------------------------- webhook + upload doors
def ingest_records(vault, org: str, source: str, records,
                   channel: str = "webhook", trust: float = 0.5) -> dict:
    """The push door: any tool POSTs records; we transform + store them.
    Goes through the SAME pipeline as everything else: LLM transform,
    provenance stamping, Rulebook trust/quarantine."""
    transformer = get_transformer()
    if isinstance(records, dict):
        records = [records]
    added, quarantined = 0, 0
    for rec in records:
        if not isinstance(rec, dict):
            rec = {"content": str(rec)}
        rec.setdefault("channel", channel)
        rec.setdefault("trust", trust)
        m = transformer.transform(rec, source)
        saved = vault.add(m, actor=f"ingest:{source}")
        added += 1
        if saved.status == "quarantined":
            quarantined += 1
    return {"source": source, "added": added, "quarantined": quarantined}


def parse_upload(filename: str, content: bytes) -> list:
    """Universal export parser: JSON (list/dict) or CSV -> raw records."""
    text = content.decode("utf-8", errors="replace")
    if filename.endswith(".csv") or ("," in text.splitlines()[0]
                                     and not text.lstrip().startswith(("[", "{"))):
        return list(csv.DictReader(io.StringIO(text)))
    data = json.loads(text)
    if isinstance(data, dict):
        for key in ("data", "records", "items", "memories", "results"):
            if isinstance(data.get(key), list):
                return data[key]
        return [data]
    return data
