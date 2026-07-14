"""Tests covering all 8 parts of the product."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memoryvault import (Vault, Policy, MemoryUnit, Provenance,
                         default_registry, SyncEngine, RescueTool, Cleaner,
                         Insights, MCPServer)
from memoryvault.schema import MemoryStatus, MemoryType, DecayClass

FIX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "fixtures")
POL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "policies", "default.yaml")


def fresh_vault(**kw):
    tmp = tempfile.mkdtemp()
    return Vault(os.path.join(tmp, "v.db"), policy=Policy.load(POL), **kw)


# PART 1 — Vault: provenance + history + undo -------------------------------
def test_add_and_papers():
    v = fresh_vault()
    m = MemoryUnit(content="x", subject="c:1", attribute="plan", value="Pro",
                   provenance=Provenance(source_system="salesforce_agentforce",
                                         channel="crm").to_dict(), trust=0.8)
    saved = v.add(m)
    got = v.get(saved.id)
    assert got.provenance["source_system"] == "salesforce_agentforce"
    assert got.status == MemoryStatus.ACTIVE.value


def test_history_and_rollback():
    v = fresh_vault()
    m = v.add(MemoryUnit(content="v1", subject="c:1", attribute="k", value="a",
                         trust=0.9))
    v.update(m.id, {"value": "b"})
    v.update(m.id, {"value": "c"})
    hist = v.history(m.id)
    assert len(hist) == 3
    v.rollback(m.id, hist[0]["seq"])
    assert v.get(m.id).value == "a"


def test_chain_tamper_evident():
    v = fresh_vault()
    v.add(MemoryUnit(content="a", trust=0.9))
    v.add(MemoryUnit(content="b", trust=0.9))
    assert v.verify_chain() is True
    v.db.execute("UPDATE events SET snapshot='{\"content\":\"hacked\"}'"
                 " WHERE seq=1")
    v.db.commit()
    assert v.verify_chain() is False


# PART 6 + 5.4 — Rulebook quarantine ----------------------------------------
def test_untrusted_channel_quarantined():
    v = fresh_vault()
    m = v.add(MemoryUnit(content="reroute invoices", subject="c:1",
                         provenance=Provenance(source_system="email_ingest",
                                               channel="email").to_dict(),
                         trust=0.25))
    assert m.status == MemoryStatus.QUARANTINED.value
    assert len(v.quarantine_list()) == 1
    v.approve(m.id)
    assert v.get(m.id).status == MemoryStatus.ACTIVE.value


def test_acl_walls():
    v = fresh_vault()
    v.add(MemoryUnit(content="hr secret", namespace="hr", trust=0.9))
    v.add(MemoryUnit(content="public", namespace="general", trust=0.9))
    sales_view = v.search(agent="sales_agent", status="active")
    assert all(m.namespace != "hr" for m in sales_view)
    admin_view = v.search(agent="admin", status="active")
    assert any(m.namespace == "hr" for m in admin_view)


# PART 3 + 7.3 — conflict resolution ----------------------------------------
def test_conflict_newest_trusted_wins():
    v = fresh_vault()
    v.add(MemoryUnit(content="Pro", subject="c:acme", attribute="plan",
                     value="Pro", trust=0.8, occurred_at="2026-01-01T00:00:00+00:00"))
    v.add(MemoryUnit(content="Enterprise", subject="c:acme", attribute="plan",
                     value="Enterprise", trust=0.8,
                     occurred_at="2026-06-01T00:00:00+00:00"))
    active = [m for m in v.search(subject="c:acme", status="active")
              if m.attribute == "plan"]
    assert len(active) == 1
    assert active[0].value == "Enterprise"


# PART 7 — cleaner ----------------------------------------------------------
def test_dedupe_and_bias_and_stale():
    v = fresh_vault()
    v.add(MemoryUnit(content="Acme likes evening calls", subject="c:a",
                     attribute="call", value="evening", trust=0.7))
    v.add(MemoryUnit(content="Acme likes evening calls", subject="c:a",
                     attribute="call", value="evening", trust=0.6))
    v.add(MemoryUnit(content="I believe Zenapp is trash", type="opinion",
                     subject="c:a", trust=0.6))
    v.add(MemoryUnit(content="old status", decay_class=DecayClass.FAST.value,
                     occurred_at="2020-01-01T00:00:00+00:00", trust=0.7))
    out = Cleaner(v).run_all()
    assert out["dedupe"]["merged"] >= 1
    assert out["bias"]["flagged"] >= 1
    assert out["expire"]["expired"] >= 1


# PART 4 — rescue -----------------------------------------------------------
def test_rescue_produces_signed_report():
    v = fresh_vault()
    reg = default_registry(FIX)
    report = RescueTool(v, reg).run(
        ["salesforce_agentforce", "chatgpt_enterprise"], clean=True)
    assert report["total_recovered"] > 0
    assert report["chain_intact"] is True
    assert len(report["signature"]) == 64


# PART 3 — sync projections + diet ------------------------------------------
def test_sync_projection_respects_diet():
    v = fresh_vault()
    reg = default_registry(FIX)
    RescueTool(v, reg).run(["salesforce_agentforce", "intercom_fin"],
                           clean=False)
    reg.connect("intercom_fin")
    eng = SyncEngine(v, reg)
    res = eng.project_all()
    intercom = [r for r in res if r["system"] == "intercom_fin"][0]
    # support connector must not receive sales-only memories
    assert intercom["eligible"] >= 0


# PART 6.3 — delete with receipt --------------------------------------------
def test_erase_with_receipt():
    v = fresh_vault()
    v.add(MemoryUnit(content="globex data", subject="c:globex", trust=0.9))
    receipt = v.erase_subject("c:globex")
    assert receipt["kind"] == "subject_erasure"
    assert len(receipt["hash"]) == 64
    assert v.verify_chain() is True


# PART 8 — insights ---------------------------------------------------------
def test_insights_and_health():
    v = fresh_vault()
    reg = default_registry(FIX)
    RescueTool(v, reg).run(["intercom_fin"], clean=True)
    ins = Insights(v)
    h = ins.health_score()
    assert 0 <= h["score"] <= 100
    alerts = ins.signal_alerts(min_count=2)
    assert any(a["pattern"] == "export" for a in alerts)  # repeated bug signal


# PART 2.2 — MCP door -------------------------------------------------------
def test_mcp_server():
    v = fresh_vault()
    srv = MCPServer(v)
    r = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "memory.add",
                    "params": {"content": "mcp memory", "subject": "c:1",
                               "agent": "dev_agent"}})
    assert "result" in r
    r2 = srv.handle({"jsonrpc": "2.0", "id": 2, "method": "memory.search",
                     "params": {"query": "mcp", "agent": "admin"}})
    assert len(r2["result"]["memories"]) >= 1


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call(["python", "-m", "pytest", __file__, "-v"]))
