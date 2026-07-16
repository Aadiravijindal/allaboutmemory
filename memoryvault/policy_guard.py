"""Policy Guard — flag memory that violates COMPANY rules (enterprise).

The company writes its own rules in plain terms; any memory that breaks one
is flagged (not silently stored), surfaced for review, and logged. This is
what turns "clean memory" into "memory compliant with how WE operate" — the
thing legal/compliance teams pay for.

Rules are declarative (kind + config), so non-engineers manage them:
  - keyword:   flag if the memory mentions any of these terms
  - regex:     flag if it matches a pattern
  - amount:    flag if a money amount exceeds a limit (e.g. refund > $500)
  - forbid_topic: flag stored advice on a forbidden topic (e.g. medical)
  - require_tier: flag if this kind of memory is stored below a tier

Each rule has a severity (info | warn | critical). A critical violation can
quarantine the memory; warn/info flag it but let it through for review.

A trained classifier can be added as another rule kind later; the evaluate()
contract stays identical.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

_MONEY = re.compile(r"(?:\$|usd|inr|eur|₹|£)\s?([\d,]+(?:\.\d+)?)|\b([\d,]+(?:\.\d+)?)\s?(?:dollars|usd|rupees|inr|eur|pounds)\b", re.I)


def _amounts(text: str) -> list:
    out = []
    for m in _MONEY.finditer(text):
        raw = m.group(1) or m.group(2)
        try:
            out.append(float(raw.replace(",", "")))
        except (ValueError, AttributeError):
            pass
    return out


@dataclass
class Rule:
    id: str
    description: str
    kind: str                        # keyword|regex|amount|forbid_topic|require_tier
    config: dict = field(default_factory=dict)
    severity: str = "warn"           # info | warn | critical
    enabled: bool = True


# A sensible starter rulebook a company edits from the UI.
DEFAULT_RULES = [
    Rule("no-big-refunds", "Never promise a refund above the approved limit",
         "amount", {"field": "content", "keywords": ["refund", "credit", "waive"],
                    "max": 500}, "critical"),
    Rule("no-medical-advice", "Agents must not store medical advice",
         "forbid_topic", {"terms": ["diagnos", "prescri", "dosage", "treatment plan"]},
         "critical"),
    Rule("no-guarantees", "Do not store absolute guarantees/promises",
         "keyword", {"terms": ["guarantee", "we promise", "100% sure", "risk-free"]},
         "warn"),
    Rule("flag-competitor-claims", "Flag disparaging competitor claims for review",
         "keyword", {"terms": ["is trash", "is garbage", "always right", "sucks"]},
         "warn"),
    Rule("secrets-stay-company-tier", "Credentials/secrets must be company-tier",
         "regex", {"pattern": r"(password|api[_ ]?key|secret|token)\s*[:=]", },
         "critical"),
]


@dataclass
class Violation:
    rule_id: str
    description: str
    severity: str
    detail: str = ""

    def to_dict(self) -> dict:
        return {"rule_id": self.rule_id, "description": self.description,
                "severity": self.severity, "detail": self.detail}


class PolicyGuard:
    def __init__(self, rules: Optional[list] = None):
        self.rules = rules if rules is not None else list(DEFAULT_RULES)

    def evaluate(self, memory) -> list:
        """Return the list of Violations this memory triggers."""
        text = (memory.content or "").lower()
        raw = memory.content or ""
        violations = []
        for r in self.rules:
            if not r.enabled:
                continue
            v = self._check(r, text, raw, memory)
            if v:
                violations.append(v)
        return violations

    def _check(self, r: Rule, text: str, raw: str, memory) -> Optional[Violation]:
        c = r.config
        if r.kind == "keyword":
            hit = next((t for t in c.get("terms", []) if t.lower() in text), None)
            if hit:
                return Violation(r.id, r.description, r.severity, f"matched '{hit}'")
        elif r.kind == "forbid_topic":
            hit = next((t for t in c.get("terms", []) if t.lower() in text), None)
            if hit:
                return Violation(r.id, r.description, r.severity, f"topic '{hit}'")
        elif r.kind == "regex":
            if re.search(c.get("pattern", "$^"), raw, re.I):
                return Violation(r.id, r.description, r.severity, "pattern matched")
        elif r.kind == "amount":
            kws = c.get("keywords", [])
            if not kws or any(k.lower() in text for k in kws):
                over = [a for a in _amounts(raw) if a > c.get("max", 1e18)]
                if over:
                    return Violation(r.id, r.description, r.severity,
                                     f"amount {max(over):.0f} over limit {c.get('max')}")
        elif r.kind == "require_tier":
            if getattr(memory, "tier", "team") != c.get("tier", "company"):
                return Violation(r.id, r.description, r.severity,
                                 f"must be {c.get('tier')} tier")
        return None

    # ---- rule management (used by the API/UI) ----------------------------
    def add_rule(self, rule: Rule):
        self.rules = [r for r in self.rules if r.id != rule.id] + [rule]

    def remove_rule(self, rule_id: str):
        self.rules = [r for r in self.rules if r.id != rule_id]

    def list_rules(self) -> list:
        return [{"id": r.id, "description": r.description, "kind": r.kind,
                 "config": r.config, "severity": r.severity, "enabled": r.enabled}
                for r in self.rules]
