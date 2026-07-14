#!/usr/bin/env python3
"""MemoryVault CLI — drive every part of the product from the terminal.

    python mv.py rescue --systems salesforce_agentforce chatgpt_enterprise intercom_fin email_ingest
    python mv.py sync
    python mv.py search "acme"
    python mv.py why <memory_id>
    python mv.py history <memory_id>
    python mv.py approvals
    python mv.py approve <memory_id>
    python mv.py clean
    python mv.py health
    python mv.py insights
    python mv.py erase customer:acme
    python mv.py rollback-since 2026-07-10T00:00:00+00:00
"""
import argparse
import json
import os
import sys

from memoryvault import (Vault, Policy, default_registry, SyncEngine,
                         RescueTool, Cleaner, Insights)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
POLICY_PATH = os.path.join(os.path.dirname(__file__), "policies", "default.yaml")


def get_vault(args):
    policy = Policy.load(POLICY_PATH if os.path.exists(POLICY_PATH) else None)
    return Vault(args.db, policy=policy, encrypt=args.encrypt)


def cmd_rescue(args):
    vault = get_vault(args)
    reg = default_registry(FIXTURES)
    tool = RescueTool(vault, reg)
    report = tool.run(args.systems, clean=not args.no_clean)
    print(RescueTool.render_report(report))
    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nFull report written to {args.json}")


def cmd_sync(args):
    vault = get_vault(args)
    reg = default_registry(FIXTURES)
    for s in args.systems or reg.available():
        try:
            reg.connect(s)
        except Exception:
            pass
    engine = SyncEngine(vault, reg)
    result = engine.sync_once()
    print(json.dumps(result, indent=2))


def cmd_search(args):
    vault = get_vault(args)
    hits = vault.search(query=args.query, agent=args.agent, limit=args.limit)
    print(f"{len(hits)} result(s) for '{args.query}' (as agent '{args.agent}'):\n")
    for m in hits:
        exp = m.expires_at or "never"
        print(f"  [{m.trust:.2f}] {m.content}")
        print(f"         id={m.id[:8]} ns={m.namespace} "
              f"from={m.provenance.get('source_system')} "
              f"status={m.status} expires={exp[:10]}")


def cmd_why(args):
    vault = get_vault(args)
    logs = vault.retrievals(memory_id=args.memory_id)
    print(f"Flight recorder — memory {args.memory_id[:8]} was used in "
          f"{len(logs)} retrieval(s):")
    for r in logs:
        print(f"  {r['ts'][:19]}  agent={r['agent']}  query='{r['query']}'")


def cmd_history(args):
    vault = get_vault(args)
    for e in vault.history(args.memory_id):
        snap = e["snapshot"]
        print(f"  seq={e['seq']:>3} {e['ts'][:19]} {e['action']:<24} "
              f"by {e['actor']}  -> value='{snap.get('value')}' "
              f"status={snap.get('status')}")


def cmd_approvals(args):
    vault = get_vault(args)
    q = vault.quarantine_list()
    print(f"Approval Room — {len(q)} memory(ies) waiting:\n")
    for m in q:
        print(f"  id={m.id[:8]} from={m.provenance.get('source_system')} "
              f"channel={m.provenance.get('channel')}")
        print(f"        \"{m.content}\"")


def cmd_approve(args):
    vault = get_vault(args)
    m = vault.approve(args.memory_id)
    print("Approved." if m else "Not found / not in quarantine.")


def cmd_reject(args):
    vault = get_vault(args)
    m = vault.reject(args.memory_id)
    print("Rejected and tombstoned." if m else "Not found.")


def cmd_clean(args):
    vault = get_vault(args)
    print(json.dumps(Cleaner(vault).run_all(), indent=2))


def cmd_health(args):
    vault = get_vault(args)
    print(json.dumps(Insights(vault).health_score(), indent=2))


def cmd_insights(args):
    vault = get_vault(args)
    ins = Insights(vault)
    print("== Learned summary ==")
    print(json.dumps(ins.learned_summary(days=args.days), indent=2))
    print("\n== Signal alerts ==")
    print(json.dumps(ins.signal_alerts(), indent=2))
    print("\n== Blind spots ==")
    print(json.dumps(ins.blind_spots(), indent=2))


def cmd_erase(args):
    vault = get_vault(args)
    receipt = vault.erase_subject(args.subject, actor="cli:gdpr")
    print("Erased with receipt:")
    print(json.dumps(receipt, indent=2))


def cmd_rollback_since(args):
    vault = get_vault(args)
    n = vault.rollback_since(args.timestamp, actor="cli:rollback")
    print(f"Rolled back {n} memory(ies) to state at {args.timestamp}.")
    print(f"Chain still intact: {vault.verify_chain()}")


def cmd_verify(args):
    vault = get_vault(args)
    print(f"Event-chain tamper check: "
          f"{'PASS' if vault.verify_chain() else 'FAIL'}")


def main():
    p = argparse.ArgumentParser(description="MemoryVault CLI")
    p.add_argument("--db", default="vault.db")
    p.add_argument("--encrypt", action="store_true",
                   help="encrypt content at rest (Feature 1.4)")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("rescue"); r.set_defaults(func=cmd_rescue)
    r.add_argument("--systems", nargs="+", default=[
        "salesforce_agentforce", "chatgpt_enterprise",
        "intercom_fin", "email_ingest"])
    r.add_argument("--no-clean", action="store_true")
    r.add_argument("--json", default=None)

    s = sub.add_parser("sync"); s.set_defaults(func=cmd_sync)
    s.add_argument("--systems", nargs="+", default=None)

    se = sub.add_parser("search"); se.set_defaults(func=cmd_search)
    se.add_argument("query")
    se.add_argument("--agent", default="admin")
    se.add_argument("--limit", type=int, default=20)

    w = sub.add_parser("why"); w.set_defaults(func=cmd_why)
    w.add_argument("memory_id")

    h = sub.add_parser("history"); h.set_defaults(func=cmd_history)
    h.add_argument("memory_id")

    ap = sub.add_parser("approvals"); ap.set_defaults(func=cmd_approvals)
    apv = sub.add_parser("approve"); apv.set_defaults(func=cmd_approve)
    apv.add_argument("memory_id")
    rj = sub.add_parser("reject"); rj.set_defaults(func=cmd_reject)
    rj.add_argument("memory_id")

    sub.add_parser("clean").set_defaults(func=cmd_clean)
    sub.add_parser("health").set_defaults(func=cmd_health)

    ins = sub.add_parser("insights"); ins.set_defaults(func=cmd_insights)
    ins.add_argument("--days", type=int, default=120)

    er = sub.add_parser("erase"); er.set_defaults(func=cmd_erase)
    er.add_argument("subject")

    rb = sub.add_parser("rollback-since"); rb.set_defaults(func=cmd_rollback_since)
    rb.add_argument("timestamp")

    sub.add_parser("verify").set_defaults(func=cmd_verify)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
