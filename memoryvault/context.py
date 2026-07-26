"""Context assembly — one memory, and every AI gets only its slice.

This is the read side of the promise. The vault holds everything: every fact
and every conversation, from every AI. But no agent ever receives all of it.
When an agent asks for context we assemble a bundle that is:

  * inside its role's namespace walls          (who-sees-what)
  * inside its sensitivity ceiling             (restricted stays home)
  * above its trust floor, bias-risk excluded  (per-target diet)
  * within a token budget, newest and most trusted first
  * recorded in the flight recorder            (we know who read what)

It returns the excluded count and the reasons alongside the payload, so a
reviewer can always see what an agent was *not* told and why.
"""
from __future__ import annotations

from .store import Vault
from .schema import MemoryStatus

# how sensitive a bundle may get, per level of the caller's clearance
_ORDER = ["public", "internal", "confidential", "restricted"]


def _rank(level: str) -> int:
    try:
        return _ORDER.index(level or "internal")
    except ValueError:
        return 1


class ContextAssembler:
    def __init__(self, vault: Vault):
        self.vault = vault

    def assemble(self, agent: str, query: str = "", subject: str = "",
                 max_facts: int = 20, max_conversations: int = 3,
                 token_budget: int = 4000,
                 clearance: str = "confidential",
                 include_transcripts: bool = True) -> dict:
        """Build one agent's view of the shared memory."""
        diet = self.vault.policy.projection(agent) or {}
        min_trust = float(diet.get("min_trust", 0.0))
        exclude_bias = bool(diet.get("exclude_bias_risk", True))
        ceiling = _rank(clearance)

        excluded = {"outside_wall_or_no_match": 0, "too_sensitive": 0,
                    "below_trust": 0, "bias_risk": 0, "budget": 0}

        # --- facts: the vault's ACL walls do the namespace filtering ---
        hits = self.vault.search(query=query, agent=agent, subject=subject or None,
                                 limit=max_facts * 4, log=False,
                                 status=MemoryStatus.ACTIVE.value)
        facts, spent = [], 0
        for m in hits:
            if _rank(m.classification) > ceiling:
                excluded["too_sensitive"] += 1
                continue
            if m.trust < min_trust:
                excluded["below_trust"] += 1
                continue
            if exclude_bias and m.bias_risk:
                excluded["bias_risk"] += 1
                continue
            cost = max(1, len(m.content) // 4)
            if spent + cost > token_budget or len(facts) >= max_facts:
                excluded["budget"] += 1
                continue
            spent += cost
            facts.append({
                "id": m.id, "content": m.content, "subject": m.subject,
                "attribute": m.attribute, "value": m.value,
                "trust": m.trust, "classification": m.classification,
                "taught_by": (m.provenance or {}).get("employee", ""),
                "from_tool": (m.provenance or {}).get("source_system", ""),
                "conversation_id": (m.provenance or {}).get("conversation_id", ""),
                "occurred_at": m.occurred_at,
            })

        # --- transcripts: the same walls, only excerpts, never the whole chat ---
        convos = []
        if include_transcripts and max_conversations > 0:
            for c in self.vault.search_conversations(
                    query=query, agent=agent, limit=max_conversations * 3,
                    log=False):
                if subject and subject not in c.subjects:
                    continue
                if _rank(c.classification) > ceiling:
                    excluded["too_sensitive"] += 1
                    continue
                if len(convos) >= max_conversations:
                    excluded["budget"] += 1
                    continue
                excerpt = self._excerpt(c, query,
                                        budget=max(200, token_budget // 8))
                spent += max(1, len(excerpt) // 4)
                convos.append({
                    "id": c.id, "external_id": c.external_id,
                    "source_system": c.source_system, "title": c.title,
                    "employee": c.employee, "started_at": c.started_at,
                    "message_count": c.message_count,
                    "classification": c.classification,
                    "excerpt": excerpt,
                })

        self.vault._log_retrieval(agent, query, [f["id"] for f in facts],
                                  "context_assembly")
        return {
            "agent": agent, "query": query, "subject": subject,
            "clearance": clearance,
            "facts": facts, "conversations": convos,
            "tokens_estimate": spent,
            "excluded": {k: v for k, v in excluded.items() if v},
            "excluded_total": sum(excluded.values()),
            "walls": self.vault.policy.allowed_namespaces(agent) or ["*"],
        }

    @staticmethod
    def _excerpt(conv, query: str, budget: int = 500) -> str:
        """Pull the part of the chat that matters instead of the whole thing."""
        msgs = conv.messages or []
        if not msgs:
            return ""
        terms = [t.lower() for t in (query or "").split() if len(t) > 2]
        best = 0
        if terms:
            scores = []
            for i, m in enumerate(msgs):
                text = str(m.get("content", "")).lower()
                scores.append(sum(1 for t in terms if t in text))
            best = max(range(len(scores)), key=lambda i: scores[i])
            if scores[best] == 0:
                best = 0
        lo = max(0, best - 1)
        out, used = [], 0
        for m in msgs[lo:lo + 4]:
            line = f"{m.get('role','?')}: {m.get('content','')}"
            if used + len(line) > budget:
                out.append(line[:max(0, budget - used)] + "…")
                break
            out.append(line)
            used += len(line)
        return "\n".join(out)

    def what_an_agent_cannot_see(self, agent: str) -> dict:
        """The reviewer's view: what this agent is walled off from."""
        allowed = self.vault.policy.allowed_namespaces(agent)
        blocked_ns, blocked_facts = set(), 0
        for m in self.vault.all_memories(status=MemoryStatus.ACTIVE.value):
            if allowed is not None and m.namespace not in allowed:
                blocked_ns.add(m.namespace)
                blocked_facts += 1
        return {"agent": agent, "can_read": allowed or ["*"],
                "blocked_namespaces": sorted(blocked_ns),
                "blocked_facts": blocked_facts}
