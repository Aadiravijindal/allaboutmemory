"""Agent-to-Agent (A2A) memory protocol.

Lets agents exchange memory over the emerging A2A standard (Linux
Foundation), not just our private API — so MemoryVault is an interoperable
node in a multi-agent mesh. Exposes an Agent Card (capability descriptor)
and typed skills to query/contribute memory, wrapping the same governed
vault (RBAC, policy, provenance all still apply).
"""
from __future__ import annotations

from .store import Vault
from .schema import MemoryUnit, Provenance


AGENT_CARD = {
    "protocolVersion": "0.2",
    "name": "MemoryVault",
    "description": "Governed, portable AI memory for the enterprise.",
    "capabilities": {"streaming": False, "pushNotifications": True},
    "skills": [
        {"id": "memory.query", "name": "Query memory",
         "description": "Search the org's governed memory.",
         "inputModes": ["text"], "outputModes": ["application/json"]},
        {"id": "memory.contribute", "name": "Contribute memory",
         "description": "Add a memory (runs through policy + approval).",
         "inputModes": ["application/json"], "outputModes": ["application/json"]},
    ],
}


class A2AHandler:
    def __init__(self, vault: Vault):
        self.vault = vault

    def agent_card(self) -> dict:
        return AGENT_CARD

    def handle(self, skill: str, params: dict, agent: str = "a2a-peer") -> dict:
        """Dispatch an A2A skill invocation against the governed vault."""
        if skill == "memory.query":
            hits = self.vault.search(query=params.get("query", ""),
                                     agent=agent, limit=int(params.get("limit", 10)),
                                     context="a2a")
            return {"memories": [m.to_dict() for m in hits]}
        if skill == "memory.contribute":
            prov = Provenance(source_system="a2a", agent_id=agent, channel="api")
            m = MemoryUnit(content=params["content"],
                           subject=params.get("subject", ""),
                           attribute=params.get("attribute", ""),
                           value=params.get("value", ""),
                           provenance=prov.to_dict(), trust=0.5)
            saved = self.vault.add(m, actor=f"a2a:{agent}")
            return {"id": saved.id, "status": saved.status}
        raise ValueError(f"unknown A2A skill: {skill}")
