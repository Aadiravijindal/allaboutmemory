"""Knowledge graph — the memory layer as connected entities, not a list.

Builds a graph from the vault: entities (customers, people, products,
internal things) as nodes, and memories as edges/attributes between them.
This is what enterprises increasingly demand (Gartner: >50% of agent
systems graph-based by 2028) — better retrieval + auditable relationships,
and the visual that makes the product click.
"""
from __future__ import annotations

from .store import Vault
from .schema import MemoryStatus
from .entities import canonical_subject, normalize_name


class KnowledgeGraph:
    def __init__(self, vault: Vault):
        self.vault = vault

    def build(self, status: str = MemoryStatus.ACTIVE.value) -> dict:
        nodes = {}   # id -> node
        edges = []

        def node(nid, label, kind):
            if nid not in nodes:
                nodes[nid] = {"id": nid, "label": label, "kind": kind,
                              "memories": 0}
            return nodes[nid]

        for m in self.vault.all_memories(status=status):
            subj = m.subject or "general"
            kind = subj.split(":")[0] if ":" in subj else "topic"
            label = subj.split(":", 1)[1] if ":" in subj else subj
            sn = node(canonical_subject(subj), label, kind)
            sn["memories"] += 1
            # link the subject to each entity the memory mentions
            for ent in (m.entities or []):
                en = node("entity:" + normalize_name(ent), ent, "entity")
                edges.append({"from": sn["id"], "to": en["id"],
                              "type": m.attribute or "mentions",
                              "value": m.value, "memory_id": m.id})
        return {"nodes": list(nodes.values()), "edges": edges,
                "stats": {"nodes": len(nodes), "edges": len(edges)}}

    def neighborhood(self, subject: str) -> dict:
        """Everything connected to one subject — for the 'who/what is linked
        to this customer' view."""
        target = canonical_subject(subject)
        g = self.build()
        connected = {target}
        for e in g["edges"]:
            if e["from"] == target:
                connected.add(e["to"])
            if e["to"] == target:
                connected.add(e["from"])
        return {
            "nodes": [n for n in g["nodes"] if n["id"] in connected],
            "edges": [e for e in g["edges"]
                      if e["from"] == target or e["to"] == target],
        }
