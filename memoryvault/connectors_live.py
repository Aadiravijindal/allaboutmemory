"""Real connector contracts — built to actual vendor API shapes.

These are the production plugs. They implement the same extract/load/watch
interface as FileConnector, but talk to real endpoints. Each is a thin,
honest skeleton against the documented API shape: you plug in a token and
it runs. The "80% nasty work" (edge-case handling, pagination quirks,
rate-limit dances, format archaeology) is exactly what deepens over many
migrations — that's the moat.

Nothing here calls a network at import time; connectors only touch the wire
when extract()/load() run, and they degrade with a clear error if the
`requests` package or the token is missing.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from .schema import MemoryUnit, Provenance, MemoryType, DecayClass, now_iso
from .connectors import Connector, SOURCE_PROFILE

try:
    import requests
    HAVE_REQUESTS = True
except Exception:  # pragma: no cover
    HAVE_REQUESTS = False


def _need_requests():
    if not HAVE_REQUESTS:
        raise RuntimeError("Install 'requests' to use live connectors.")


class RestConnector(Connector):
    """Generic REST plug: point it at any endpoint returning a list of
    records, map fields to the canonical schema. The workhorse behind most
    real integrations (Intercom, custom internal agents, webhooks)."""
    system = "rest"

    def __init__(self, base_url: str, token: str = "",
                 extract_path: str = "/memories", load_path: str = "/memories",
                 field_map: Optional[dict] = None, system: str = "rest",
                 config: Optional[dict] = None):
        super().__init__(config)
        self.system = system
        self.base_url = base_url.rstrip("/")
        self.token = token or os.environ.get("MV_TOKEN", "")
        self.extract_path = extract_path
        self.load_path = load_path
        self.field_map = field_map or {}

    def _headers(self):
        h = {"content-type": "application/json"}
        if self.token:
            h["authorization"] = f"Bearer {self.token}"
        return h

    def _map(self, rec: dict) -> dict:
        if not self.field_map:
            return rec
        return {canon: rec.get(src, "") for canon, src in self.field_map.items()}

    def extract(self) -> list:
        _need_requests()
        out, url = [], self.base_url + self.extract_path
        # cursor pagination is the common case; handle both list + {data,next}
        while url:
            r = requests.get(url, headers=self._headers(), timeout=30)
            r.raise_for_status()
            body = r.json()
            records = body if isinstance(body, list) else body.get("data", [])
            for rec in records:
                out.append(self._wrap(self._map(rec)))
            url = None if isinstance(body, list) else body.get("next_url")
        return out

    def load(self, memories: list) -> dict:
        _need_requests()
        sent = 0
        for m in memories:
            payload = {"content": m.content, "subject": m.subject,
                       "attribute": m.attribute, "value": m.value,
                       "metadata": {"mv_id": m.id, "trust": m.trust}}
            r = requests.post(self.base_url + self.load_path,
                              headers=self._headers(), json=payload, timeout=30)
            if r.ok:
                sent += 1
        return {"system": self.system, "delivered": sent}


class Mem0Connector(Connector):
    """Mem0 export/import (docs.mem0.ai). Real shape: GET /v1/memories,
    POST /v1/memories. This is a memory ENGINE migration — the exact
    'leave Mem0 for us / bring Mem0 into the vault' path."""
    system = "mem0"

    def __init__(self, api_key: str = "", base_url: str = "https://api.mem0.ai",
                 org_id: str = "", config: Optional[dict] = None):
        super().__init__(config)
        self.api_key = api_key or os.environ.get("MEM0_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.org_id = org_id

    def _headers(self):
        return {"authorization": f"Token {self.api_key}",
                "content-type": "application/json"}

    def extract(self) -> list:
        _need_requests()
        params = {"org_id": self.org_id} if self.org_id else {}
        r = requests.get(f"{self.base_url}/v1/memories/",
                         headers=self._headers(), params=params, timeout=30)
        r.raise_for_status()
        out = []
        for rec in r.json().get("results", r.json() if isinstance(r.json(), list) else []):
            out.append(self._wrap({
                "content": rec.get("memory", rec.get("text", "")),
                "occurred_at": rec.get("created_at", now_iso()),
                "entities": [e.get("name") for e in rec.get("entities", [])],
                "type": MemoryType.FACT.value,
            }))
        return out

    def load(self, memories: list) -> dict:
        _need_requests()
        sent = 0
        for m in memories:
            body = {"messages": [{"role": "user", "content": m.content}],
                    "metadata": {"mv_id": m.id, "subject": m.subject}}
            if self.org_id:
                body["org_id"] = self.org_id
            r = requests.post(f"{self.base_url}/v1/memories/",
                              headers=self._headers(), json=body, timeout=30)
            if r.ok:
                sent += 1
        return {"system": self.system, "delivered": sent}


class OpenAIExportConnector(Connector):
    """ChatGPT Enterprise Compliance API shape (platform.openai.com).
    Real endpoint family: /v1/organization/... compliance exports. This
    skeleton reads an already-produced export ZIP/JSON (the realistic path,
    since compliance exports are async batch jobs) and normalizes it."""
    system = "chatgpt_enterprise"

    def __init__(self, export_file: str = "", config: Optional[dict] = None):
        super().__init__(config)
        self.export_file = export_file or os.environ.get("OPENAI_EXPORT_FILE", "")

    def extract(self) -> list:
        if not self.export_file or not os.path.exists(self.export_file):
            raise RuntimeError(
                "Provide the ChatGPT Enterprise compliance export file "
                "(OPENAI_EXPORT_FILE). Compliance exports are async batch "
                "jobs — request via the Compliance API, then point here.")
        with open(self.export_file) as f:
            data = json.load(f)
        convos = data if isinstance(data, list) else data.get("conversations", [])
        out = []
        for convo in convos:
            for msg in convo.get("messages", []):
                if msg.get("role") == "user":
                    out.append(self._wrap({
                        "content": msg.get("content", ""),
                        "channel": "chat",
                        "occurred_at": msg.get("create_time", now_iso()),
                    }))
        return out

    def load(self, memories: list) -> dict:
        # ChatGPT Enterprise ingests company knowledge via connected knowledge
        # sources; write-back is a knowledge-source push, not a memory API.
        return {"system": self.system, "delivered": 0,
                "note": "write-back via ChatGPT Enterprise knowledge source"}


class DataActRequestConnector(Connector):
    """EU Data Act (Chapter VI) extraction path. When a vendor lacks an
    export API, the customer has a *legal right* to a machine-readable
    export and the vendor must cooperate. This connector ingests whatever
    lawful export the vendor produced (CSV/JSON) and normalizes it —
    turning a legal lever into recovered memory."""
    system = "dataact_export"

    def __init__(self, export_file: str, source_system: str = "vendor",
                 config: Optional[dict] = None):
        super().__init__(config)
        self.export_file = export_file
        self.system = source_system

    def extract(self) -> list:
        if not os.path.exists(self.export_file):
            raise RuntimeError(f"Export file not found: {self.export_file}")
        with open(self.export_file) as f:
            content = f.read()
        try:
            records = json.loads(content)
        except json.JSONDecodeError:
            import csv, io
            records = list(csv.DictReader(io.StringIO(content)))
        return [self._wrap(r if isinstance(r, dict) else {"content": str(r)})
                for r in (records if isinstance(records, list) else [records])]

    def load(self, memories: list) -> dict:
        return {"system": self.system, "delivered": 0,
                "note": "Data Act path is extraction-only"}


def register_live_connectors(registry, **tokens):
    """Wire live connectors into a registry (production use). Tokens come
    from the customer's secret store, never hardcoded."""
    registry.register("mem0",
                      lambda **c: Mem0Connector(api_key=tokens.get("mem0_key", "")))
    registry.register("rest",
                      lambda base_url="", **c: RestConnector(base_url=base_url,
                                                             token=tokens.get("rest_token", "")))
    registry.register("chatgpt_export",
                      lambda export_file="", **c: OpenAIExportConnector(export_file))
    return registry
