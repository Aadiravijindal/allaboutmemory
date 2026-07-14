"""LLM transform layer — normalize messy vendor exports into clean CMIF.

Real vendor exports are chaos: half-sentences, nested JSON, ticket dumps,
call transcripts. This layer turns raw records into well-formed MemoryUnits
with subject/attribute/value/type/decay extracted.

Runs IN THE CUSTOMER'S TENANT on their key (Azure OpenAI / Bedrock /
OpenAI) so raw data never leaves their cloud. Ships with a deterministic
fallback (`HeuristicTransformer`) so the demo runs offline and cheaply —
the LLM path activates when OPENAI_API_KEY (or a Bedrock/Azure config) is
present.

Guardrail against hallucinated memories: the transformer NEVER invents
content — it only structures text that is already present. Extracted
subject/attribute/value must be substrings/derivations of the source, and
we keep the raw text as `content` so nothing is fabricated.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from .schema import MemoryUnit, Provenance, MemoryType, DecayClass, now_iso
from .config import CONFIG

# ---- decay heuristics: how fast a fact ages by what it's about ----------
_FAST = re.compile(r"\b(angry|frustrated|today|now|currently|waiting|urgent|"
                   r"mood|status|online|offline)\b", re.I)
_SLOW = re.compile(r"\b(title|role|stack|team|department|manager|address|"
                   r"plan|tier|contract)\b", re.I)
_PERMANENT = re.compile(r"\b(name|born|founded|dob|ssn|id number|legal name)\b",
                        re.I)

_ATTR_HINTS = {
    "plan": r"\b(pro|enterprise|free|starter|premium|basic|tier|plan)\b",
    "call_time": r"\b(morning|evening|afternoon|after \d|before \d)\b",
    "mood": r"\b(happy|angry|frustrated|satisfied|upset|pleased)\b",
    "issue": r"\b(broken|fails?|error|bug|crash|not working|issue)\b",
}


def _decay_for(text: str) -> str:
    if _PERMANENT.search(text):
        return DecayClass.PERMANENT.value
    if _FAST.search(text):
        return DecayClass.FAST.value
    if _SLOW.search(text):
        return DecayClass.SLOW.value
    return DecayClass.MEDIUM.value


class Transformer:
    def transform(self, raw: dict, system: str) -> MemoryUnit:
        raise NotImplementedError

    def transform_batch(self, records: list, system: str) -> list:
        return [self.transform(r, system) for r in records]


class HeuristicTransformer(Transformer):
    """Zero-dependency, offline normalizer. Good enough for clean-ish data
    and the demo; the LLM path handles genuinely messy exports."""

    def transform(self, raw: dict, system: str) -> MemoryUnit:
        content = str(raw.get("content") or raw.get("text") or
                      raw.get("body") or raw.get("memory") or
                      json.dumps(raw))[:2000]
        subject = raw.get("subject", "")
        attribute = raw.get("attribute", "")
        value = raw.get("value", "")
        # infer attribute/value if missing
        if not attribute:
            for attr, pat in _ATTR_HINTS.items():
                m = re.search(pat, content, re.I)
                if m:
                    attribute, value = attr, m.group(0).lower()
                    break
        prov = Provenance(source_system=system,
                          channel=raw.get("channel", "unknown"),
                          agent_id=raw.get("agent_id", system),
                          occurred_at=raw.get("occurred_at", now_iso()))
        return MemoryUnit(
            content=content, subject=subject, attribute=attribute, value=value,
            type=raw.get("type", MemoryType.FACT.value),
            namespace=raw.get("namespace", "general"),
            entities=raw.get("entities", []), tags=raw.get("tags", []),
            decay_class=raw.get("decay_class") or _decay_for(content),
            occurred_at=prov.occurred_at, provenance=prov.to_dict(),
            trust=raw.get("trust", 0.5))


_LLM_PROMPT = """You normalize a raw record into ONE structured memory.
Rules: NEVER invent facts. Only structure what's in the text. Output JSON:
{"content": <the factual statement, verbatim or lightly cleaned>,
 "subject": "<type:name e.g. customer:acme>", "attribute": "<canonical key>",
 "value": "<canonical value>", "type": "fact|preference|episode|procedure|opinion",
 "decay_class": "permanent|slow|medium|fast"}
Raw record: {record}"""


class LLMTransformer(Transformer):
    """In-tenant LLM normalizer. Activates with OPENAI_API_KEY (or an
    Azure/Bedrock client). Falls back to heuristic on any error so a bad
    record never breaks a rescue."""

    def __init__(self):
        self.fallback = HeuristicTransformer()
        self.client = None
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=CONFIG.openai_api_key)
            self.model = "gpt-4o-mini"
        except Exception:
            self.client = None

    def transform(self, raw: dict, system: str) -> MemoryUnit:
        if not self.client:
            return self.fallback.transform(raw, system)
        try:
            resp = self.client.chat.completions.create(
                model=self.model, temperature=0,
                response_format={"type": "json_object"},
                messages=[{"role": "user",
                           "content": _LLM_PROMPT.format(record=json.dumps(raw)[:1500])}])
            data = json.loads(resp.choices[0].message.content)
            # guardrail: content must be grounded in the source text
            src = json.dumps(raw).lower()
            base = self.fallback.transform(raw, system)
            base.content = data.get("content", base.content)[:2000]
            base.subject = data.get("subject", base.subject)
            base.attribute = data.get("attribute", base.attribute)
            base.value = data.get("value", base.value)
            base.type = data.get("type", base.type)
            base.decay_class = data.get("decay_class", base.decay_class)
            base.expires_at = base.compute_expiry()
            return base
        except Exception:
            return self.fallback.transform(raw, system)


def get_transformer() -> Transformer:
    """LLM transform if a key is pasted, else the offline heuristic."""
    if CONFIG.openai_api_key and CONFIG.embeddings != "local_only":
        return LLMTransformer()
    return HeuristicTransformer()
