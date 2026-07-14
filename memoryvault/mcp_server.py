"""Feature 2.2 — One simple door for custom agents (MCP + API).

A minimal JSON-RPC style handler exposing the vault to any MCP-capable
agent (Claude, Cursor, Codex, custom). This is the "one line of setup"
door: a developer's own agent gets company-grade memory — with the
Rulebook, Approval Room, and flight recorder all applied automatically —
instead of building their own memory layer.

Kept dependency-free (stdin/stdout JSON) so it runs anywhere; a real
deployment wraps the same handlers in the official MCP SDK transport.
"""
from __future__ import annotations

import json
import sys

from .store import Vault
from .schema import MemoryUnit, Provenance

TOOLS = [
    {"name": "memory.search",
     "description": "Search the company vault (ACL + flight-recorder applied).",
     "params": {"query": "str", "agent": "str", "limit": "int"}},
    {"name": "memory.add",
     "description": "Write a memory (goes through Approval Room if untrusted).",
     "params": {"content": "str", "subject": "str", "attribute": "str",
                "value": "str", "agent": "str"}},
    {"name": "memory.get",
     "description": "Fetch one memory with its full provenance.",
     "params": {"id": "str"}},
    {"name": "memory.why",
     "description": "Flight recorder: which memories an agent recently used.",
     "params": {"agent": "str"}},
]


class MCPServer:
    def __init__(self, vault: Vault, agent_default: str = "custom_mcp"):
        self.vault = vault
        self.agent_default = agent_default

    def handle(self, req: dict) -> dict:
        method = req.get("method")
        p = req.get("params", {}) or {}
        rid = req.get("id")
        try:
            result = self._dispatch(method, p)
            return {"jsonrpc": "2.0", "id": rid, "result": result}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": rid,
                    "error": {"message": str(e)}}

    def _dispatch(self, method: str, p: dict):
        if method in ("tools/list", "list_tools"):
            return {"tools": TOOLS}
        if method in ("memory.search", "tools/call:memory.search"):
            hits = self.vault.search(
                query=p.get("query", ""),
                agent=p.get("agent", self.agent_default),
                limit=int(p.get("limit", 10)),
                context="mcp")
            return {"memories": [m.to_dict() for m in hits]}
        if method == "memory.get":
            m = self.vault.get(p["id"])
            return {"memory": m.to_dict() if m else None}
        if method == "memory.add":
            prov = Provenance(source_system="custom_mcp",
                              agent_id=p.get("agent", self.agent_default),
                              channel="api")
            m = MemoryUnit(content=p["content"], subject=p.get("subject", ""),
                           attribute=p.get("attribute", ""),
                           value=p.get("value", ""),
                           namespace=p.get("namespace", "general"),
                           provenance=prov.to_dict(), trust=0.6)
            saved = self.vault.add(m, actor=f"mcp:{prov.agent_id}")
            return {"id": saved.id, "status": saved.status}
        if method == "memory.why":
            return {"retrievals": self.vault.retrievals(
                agent=p.get("agent"), limit=20)}
        raise ValueError(f"Unknown method: {method}")

    def serve_stdio(self):  # pragma: no cover
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            resp = self.handle(json.loads(line))
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
