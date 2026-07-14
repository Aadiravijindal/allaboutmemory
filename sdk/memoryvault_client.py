"""MemoryVault Python SDK — the developer's one-line door.

    from memoryvault_client import MemoryVault
    mv = MemoryVault("https://vault.acme.com", api_key="mv_...")
    mv.add("Customer prefers evening calls", subject="customer:acme",
           attribute="call_time", value="evening")
    for m in mv.search("acme"):
        print(m["content"])

This is the SDK an internal agent uses to read/write the company brain —
governance, approval room, and flight recorder apply automatically.
"""
from __future__ import annotations

from typing import Optional

try:
    import requests
except Exception:  # pragma: no cover
    requests = None


class MemoryVault:
    def __init__(self, base_url: str, api_key: str):
        if requests is None:
            raise RuntimeError("pip install requests")
        self.base = base_url.rstrip("/")
        self.h = {"x-api-key": api_key, "content-type": "application/json"}

    def _get(self, path, **params):
        r = requests.get(self.base + path, headers=self.h, params=params,
                         timeout=30)
        r.raise_for_status()
        return r.json()

    def _post(self, path, body=None, **params):
        r = requests.post(self.base + path, headers=self.h, json=body or {},
                          params=params, timeout=60)
        r.raise_for_status()
        return r.json()

    # ---- memories --------------------------------------------------------
    def add(self, content: str, subject: str = "", attribute: str = "",
            value: str = "", namespace: str = "general", type: str = "fact",
            trust: float = 0.6, source_system: str = "sdk",
            channel: str = "api", tags: Optional[list] = None) -> dict:
        return self._post("/api/memories", {
            "content": content, "subject": subject, "attribute": attribute,
            "value": value, "namespace": namespace, "type": type,
            "trust": trust, "source_system": source_system,
            "channel": channel, "tags": tags or []})

    def search(self, query: str = "", agent: str = "admin",
               limit: int = 50) -> list:
        return self._get("/api/memories", q=query, agent=agent,
                         limit=limit)["memories"]

    def get(self, memory_id: str) -> dict:
        return self._get(f"/api/memories/{memory_id}")

    def history(self, memory_id: str) -> list:
        return self._get(f"/api/memories/{memory_id}/history")["history"]

    def why(self, memory_id: str) -> list:
        return self._get(f"/api/memories/{memory_id}/why")["retrievals"]

    def delete(self, memory_id: str) -> dict:
        r = requests.delete(f"{self.base}/api/memories/{memory_id}",
                            headers=self.h, timeout=30)
        r.raise_for_status()
        return r.json()

    def erase_subject(self, subject: str) -> dict:
        return self._post("/api/erase", subject=subject)

    # ---- operations ------------------------------------------------------
    def rescue(self, systems: list, clean: bool = True) -> dict:
        return self._post("/api/rescue", {"systems": systems, "clean": clean})

    def sync(self) -> dict:
        return self._post("/api/sync")

    def clean(self) -> dict:
        return self._post("/api/clean")

    def health_score(self) -> dict:
        return self._get("/api/health-score")

    def insights(self, days: int = 180) -> dict:
        return self._get("/api/insights", days=days)

    def approvals(self) -> list:
        return self._get("/api/approvals")["memories"]

    def approve(self, memory_id: str) -> dict:
        return self._post(f"/api/approvals/{memory_id}/approve")
