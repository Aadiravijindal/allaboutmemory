#!/usr/bin/env python3
"""End-to-end demo — the whole product story in one run.

Shows every one of the 8 parts working together on the sample data:
Rescue -> Sync -> Approval Room -> Cleaner (contradiction/dedupe/bias/
staleness) -> Search with flight recorder -> History + Undo ->
Delete-with-receipt -> Insights.

    python demo.py
"""
import os
import tempfile

from memoryvault import (Vault, Policy, default_registry, SyncEngine,
                         RescueTool, Cleaner, Insights)

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
POL = os.path.join(os.path.dirname(__file__), "policies", "default.yaml")


def line(t=""):
    print(t)


def rule(t):
    print("\n" + "=" * 66 + f"\n  {t}\n" + "=" * 66)


def main():
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "vault.db")
    vault = Vault(db, policy=Policy.load(POL), encrypt=False)
    reg = default_registry(FIX)

    rule("PART 4 — RESCUE: pull trapped memory out of every platform")
    tool = RescueTool(vault, reg)
    report = tool.run(["salesforce_agentforce", "chatgpt_enterprise",
                       "intercom_fin", "email_ingest"], clean=False)
    print(RescueTool.render_report(report))

    rule("PART 6 + 5.4 — RULEBOOK held the sketchy email memories for review")
    for m in vault.quarantine_list():
        print(f"  HELD: \"{m.content}\"")
        print(f"        (from {m.provenance['source_system']} via "
              f"{m.provenance['channel']} — untrusted)")
    line("\n  The invoice-reroute email is a classic memory-poisoning attempt.")
    line("  It never reached the AI's brain. On every other system it would have.")

    rule("PART 7 — CLEANER: contradictions, duplicates, staleness, bias")
    before = vault.counts()
    result = Cleaner(vault).run_all()
    print(f"  dedupe:        {result['dedupe']}")
    print(f"  freshness:     {result['expire']}")
    print(f"  contradictions:{result['contradictions']}")
    print(f"  yes-man filter:{result['bias']}")
    line(f"\n  counts before: {before}")
    line(f"  counts after : {vault.counts()}")

    rule("3.2 — Which plan does the AI now believe Acme is on?")
    hits = vault.search(subject="customer:acme", agent="admin",
                        context="demo:plan-question")
    for m in hits:
        if m.attribute == "plan":
            print(f"  WINNER: Acme plan = {m.value}  "
                  f"(trust {m.trust:.2f}, {m.occurred_at[:10]}, "
                  f"status {m.status})")
    line("  Salesforce said 'Pro' (Jan). ChatGPT said 'Enterprise' (Jun).")
    line("  Newest + trusted wins; the old one is kept in history, not lost.")

    rule("PART 3 — SYNC: give every AI the one shared brain (on its diet)")
    for s in ["salesforce_agentforce", "chatgpt_enterprise", "intercom_fin"]:
        reg.connect(s)
    engine = SyncEngine(vault, reg)
    out = engine.project_all()
    for r in out:
        print(f"  -> {r['system']:<24} delivered {r.get('delivered',0)} "
              f"memories (eligible {r.get('eligible',0)})")
    line("\n  Support AI (intercom) got support+general only — NOT sales/HR.")
    line("  That's the per-AI diet (Feature 3.3) enforced by the Rulebook.")

    rule("6.4 — FLIGHT RECORDER: why did the AI know Acme's plan?")
    recs = vault.retrievals(limit=5)
    for r in recs:
        print(f"  {r['ts'][:19]}  agent={r['agent']}  context='{r['context']}'"
              f"  -> {len(r['memory_ids'])} memories used")
    if not recs:
        print("  (no retrievals logged yet)")

    rule("1.3 + UNDO — the diary and rollback")
    plan_mem = [m for m in vault.all_memories()
                if m.attribute == "plan" and m.status == "active"]
    if plan_mem:
        mid = plan_mem[0].id
        print(f"  History of memory {mid[:8]}:")
        for e in vault.history(mid):
            print(f"    seq {e['seq']}: {e['action']} -> "
                  f"{e['snapshot'].get('status')}")

    rule("6.3 — DELETE-WITH-RECEIPT: 'erase everything about Globex'")
    receipt = vault.erase_subject("customer:globex", actor="demo:gdpr")
    print(f"  Receipt {receipt['id'][:8]} ({receipt['kind']})")
    print(f"    erased {len(receipt['memory_ids'])} memories")
    print(f"    hash {receipt['hash'][:32]}…")
    print(f"    chain intact after erasure: {vault.verify_chain()}")

    rule("PART 8 — INSIGHTS + 5.3 HEALTH SCORE")
    ins = Insights(vault)
    h = ins.health_score()
    print(f"  Health score: {h['score']} ({h['grade']})  "
          f"freshness={h['freshness']} cleanliness={h['cleanliness']} "
          f"bias_flags={h['bias_flags']}")
    line("\n  Signal alerts (a pattern leadership should see):")
    for a in ins.signal_alerts(min_count=2):
        print(f"    {a['count']}× '{a['pattern']}'  e.g. \"{a['example']}\"")
    line("\n  Blind-spot map:")
    for ns, d in ins.blind_spots().items():
        print(f"    {ns:<14} {d['count']} mem, avg {d['avg_age_days']}d, "
              f"risk={d['risk']}")

    rule("TAMPER CHECK — the whole event chain")
    print(f"  verify_chain(): {'PASS ✅' if vault.verify_chain() else 'FAIL ❌'}")
    line(f"\n  Vault DB at: {db}")
    line("  Run the Control Room:  MV_DB=%s python dashboard.py" % db)


if __name__ == "__main__":
    main()
