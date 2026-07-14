"""PART 4 — THE RESCUE TOOL. Day-one magic.

  4.1 The extraction  -> pull trapped memory out of every vendor
  4.2 The verification report -> signed proof of what moved

This is the paid onboarding flow: point it at a company's connected
platforms, it pulls everything into the vault they own, cleans it, and
emits a report their manager can forward to their boss.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from .store import Vault
from .sync import SyncEngine
from .cleaner import Cleaner
from .connectors import ConnectorRegistry


class RescueTool:
    def __init__(self, vault: Vault, registry: ConnectorRegistry):
        self.vault = vault
        self.registry = registry
        self.sync = SyncEngine(vault, registry)

    def run(self, systems: list, clean: bool = True) -> dict:
        started = datetime.now(timezone.utc).isoformat()
        per_system = []
        recovered_total = 0

        for system in systems:
            try:
                conn = self.registry.connect(system)
                mems = conn.extract()
                loaded, quarantined = 0, 0
                for m in mems:
                    saved = self.vault.add(m, actor=f"rescue:{system}")
                    if saved.status == "quarantined":
                        quarantined += 1
                    loaded += 1
                recovered_total += loaded
                per_system.append({
                    "system": system, "recovered": loaded,
                    "quarantined_for_review": quarantined,
                    "status": "ok",
                })
            except Exception as e:  # honest reporting of what failed (4.2)
                per_system.append({
                    "system": system, "recovered": 0,
                    "status": "failed", "reason": str(e),
                })

        cleaning = self.cleaner_pass() if clean else None
        finished = datetime.now(timezone.utc).isoformat()

        report = {
            "report_type": "MemoryVault Rescue Verification",
            "started_at": started, "finished_at": finished,
            "systems": per_system,
            "total_recovered": recovered_total,
            "cleaning": cleaning,
            "vault_counts": self.vault.counts(),
            "chain_intact": self.vault.verify_chain(),
        }
        # sign the report against the current event-chain head
        report["chain_head"] = self.vault._last_hash()
        report["signature"] = hashlib.sha256(
            json.dumps(report, sort_keys=True).encode()).hexdigest()
        return report

    def cleaner_pass(self) -> dict:
        return Cleaner(self.vault).run_all()

    @staticmethod
    def render_report(report: dict) -> str:
        lines = []
        a = lines.append
        a("=" * 62)
        a("  " + report["report_type"])
        a("=" * 62)
        a(f"  Started : {report['started_at']}")
        a(f"  Finished: {report['finished_at']}")
        a(f"  Chain intact (tamper check): {report['chain_intact']}")
        a("-" * 62)
        a("  RECOVERED PER SYSTEM")
        for s in report["systems"]:
            if s["status"] == "ok":
                a(f"    - {s['system']:<24} {s['recovered']:>5} memories"
                  f"  ({s['quarantined_for_review']} held for review)")
            else:
                a(f"    - {s['system']:<24}  FAILED: {s['reason']}")
        a("-" * 62)
        a(f"  TOTAL RECOVERED: {report['total_recovered']} memories")
        if report.get("cleaning"):
            c = report["cleaning"]
            a(f"  Cleaned: {c['dedupe']['merged']} duplicates merged, "
              f"{c['expire']['expired']} stale retired, "
              f"{c['contradictions']['resolved']} contradictions resolved")
        a("-" * 62)
        a("  VAULT STATE: " + ", ".join(
            f"{k}={v}" for k, v in report["vault_counts"].items()))
        a(f"  Signature: {report['signature'][:32]}...")
        a("=" * 62)
        return "\n".join(lines)
