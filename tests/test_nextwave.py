"""Tests for the next-wave enterprise features: ROI, quality evals, data
classification + no-training, zero-data-retention, real-time write-back,
knowledge graph, consent ledger, A2A protocol, model router, integrations."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memoryvault import Vault, Policy, MemoryUnit, Provenance
from memoryvault.roi import ROI
from memoryvault.evals import Evals
from memoryvault.graph import KnowledgeGraph
from memoryvault.classification import classify, training_allowed, routing_allowed
from memoryvault.consent import ConsentLedger, enforce_withdrawals
from memoryvault.models import ModelRouter, MODEL_REGISTRY
from memoryvault.a2a import A2AHandler
from memoryvault.integrations import catalog, live
from memoryvault.realtime import RealtimeBus

POL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "policies", "default.yaml")


def vault(**kw):
    return Vault(os.path.join(tempfile.mkdtemp(), "v.db"),
                 policy=Policy.load(POL), **kw)


def seed(v, n=3):
    for i in range(n):
        v.add(MemoryUnit(
            content=f"customer:acme prefers plan pro variant {i}",
            subject="customer:acme", attribute="plan", value=f"pro-{i}",
            entities=["acme", "billing"], trust=0.8,
            provenance=Provenance(source_system="chatgpt",
                                  employee="jordan").to_dict()))
    return v


# ---- ROI -----------------------------------------------------------------
def test_roi_produces_dollar_number():
    v = seed(vault())
    # generate some retrievals so reuse value is non-zero
    v.search(query="plan", agent="owner")
    v.search(query="acme", agent="owner")
    out = ROI(v).summary()
    assert out["total_value_usd"] >= 0
    assert "reuse_value_usd" in out["breakdown"]
    assert out["drivers"]["memories_reused"] >= 1
    assert out["assumptions"]["loaded_hourly_cost"] == 60


def test_roi_respects_custom_rates():
    v = seed(vault())
    v.search(query="plan", agent="owner")
    base = ROI(v).summary()["breakdown"]["reuse_value_usd"]
    pricey = ROI(v, rates={"loaded_hourly_cost": 600}).summary()
    assert pricey["breakdown"]["reuse_value_usd"] >= base


# ---- Evals ---------------------------------------------------------------
def test_evals_scores_and_grades():
    v = seed(vault())
    out = Evals(v).score()
    assert 0 <= out["overall"] <= 100
    assert out["grade"] in ("A", "B", "C", "D", "F")
    assert set(out["dimensions"]) == {
        "freshness", "consistency", "provenance", "honesty", "hygiene"}


def test_evals_recall_set():
    v = seed(vault())
    res = Evals(v).run_eval_set(
        [{"query": "plan", "expect_substring": "pro"},
         {"query": "nonsense-zzz", "expect_substring": "nope"}], agent="owner")
    assert res["cases"] == 2
    assert 0.0 <= res["recall_at_5"] <= 1.0


# ---- Data classification -------------------------------------------------
def test_classification_levels():
    restricted = MemoryUnit(content="patient SSN 123-45-6789 medical record")
    conf = MemoryUnit(content="Q3 revenue pricing roadmap", namespace="general")
    internal = MemoryUnit(content="team standup notes", subject="topic:ops",
                          namespace="general")
    assert classify(restricted) == "restricted"
    assert classify(conf) == "confidential"
    assert classify(internal) == "internal"


def test_classification_gates_training_and_routing():
    restricted = MemoryUnit(content="password is hunter2 secret")
    restricted.classification = classify(restricted)
    assert routing_allowed(restricted) is False
    # even with training turned on, restricted never trains
    assert training_allowed(restricted, {"allow_training": True}) is False
    public = MemoryUnit(content="the office opens at 9am")
    public.classification = "public"
    assert training_allowed(public, {"allow_training": True}) is True
    assert training_allowed(public, {"allow_training": False}) is False


def test_classification_set_on_write():
    v = vault()
    m = v.add(MemoryUnit(content="employee salary is 150k", trust=0.8))
    assert v.get(m.id).classification == "restricted"


# ---- Zero-data-retention -------------------------------------------------
def test_zero_retention_drops_content():
    v = vault(zero_retention=True)
    m = v.add(MemoryUnit(content="super sensitive raw text",
                         subject="customer:x", attribute="note", value="v",
                         trust=0.8))
    got = v.get(m.id)
    assert "raw text" not in got.content
    assert got.redacted is True
    # governance metadata still present
    assert got.subject == "customer:x" and got.classification


# ---- Real-time write-back ------------------------------------------------
def test_realtime_fires_on_write():
    fired = []
    v = vault(event_hook=lambda action, mem: fired.append((action, mem)))
    v.add(MemoryUnit(content="new fact", subject="customer:acme",
                     attribute="tier", value="gold", trust=0.9))
    assert fired and fired[0][0] == "add"
    assert fired[0][1]["subject"] == "customer:acme"


def test_realtime_hook_error_never_breaks_write():
    def boom(action, mem):
        raise RuntimeError("subscriber down")
    v = vault(event_hook=boom)
    m = v.add(MemoryUnit(content="still saved", trust=0.9))
    assert v.get(m.id) is not None  # write survived a bad subscriber


def test_realtime_quarantined_not_fired():
    fired = []
    v = vault(event_hook=lambda a, m: fired.append(a))
    # untrusted channel -> quarantined -> should NOT push
    v.add(MemoryUnit(content="from the web", trust=0.1,
                     provenance=Provenance(source_system="web",
                                          channel="web").to_dict()))
    assert fired == []


def test_realtime_bus_subscribe_list_unsubscribe():
    bus = RealtimeBus(tempfile.mkdtemp())
    sub = bus.subscribe("https://example.com/hook", ["add"])
    assert "secret" not in sub
    assert len(bus.list()) == 1
    assert bus.unsubscribe(sub["id"]) is True
    assert bus.list() == []


# ---- Knowledge graph -----------------------------------------------------
def test_graph_builds_nodes_and_edges():
    v = seed(vault())
    g = KnowledgeGraph(v).build()
    assert g["stats"]["nodes"] >= 1
    assert g["stats"]["edges"] >= 1
    kinds = {n["kind"] for n in g["nodes"]}
    assert "customer" in kinds


def test_graph_neighborhood():
    v = seed(vault())
    nb = KnowledgeGraph(v).neighborhood("customer:acme")
    labels = {n["label"] for n in nb["nodes"]}
    assert "acme" in labels


# ---- Consent -------------------------------------------------------------
def test_consent_grant_and_withdraw():
    led = ConsentLedger(tempfile.mkdtemp())
    assert led.has_consent("customer:acme") is True   # default allow
    led.set("customer:acme", False, actor="dpo")
    assert led.has_consent("customer:acme") is False
    assert "customer:acme" in led.withdrawn()


def test_consent_enforcement_purges_memory():
    v = seed(vault())
    led = ConsentLedger(tempfile.mkdtemp())
    led.set("customer:acme", False)
    out = enforce_withdrawals(v, led)
    assert out["subjects_purged"] == 1
    active = [m for m in v.all_memories(status="active")
              if m.subject == "customer:acme"]
    assert active == []


# ---- Model router --------------------------------------------------------
def test_model_router_surfaces_deprecations():
    r = ModelRouter()
    notes = r.deprecation_notices()
    assert any(n["model"] == "gpt-4-turbo" for n in notes)
    assert r.is_allowed("claude-opus-4-8")


def test_model_router_pinned_set():
    r = ModelRouter(allowed=["claude-opus-4-8"])
    assert r.is_allowed("claude-opus-4-8")
    assert r.is_allowed("gpt-4o") is False
    assert r.deprecation_notices() == []  # none of the pinned are deprecated


# ---- A2A -----------------------------------------------------------------
def test_a2a_agent_card():
    v = seed(vault())
    card = A2AHandler(v).agent_card()
    assert card["name"] == "MemoryVault"
    skills = {s["id"] for s in card["skills"]}
    assert {"memory.query", "memory.contribute"} <= skills


def test_a2a_query_returns_memories_for_owner():
    v = seed(vault())
    out = A2AHandler(v).handle("memory.query", {"query": "plan"}, agent="owner")
    assert len(out["memories"]) >= 1


def test_a2a_contribute_runs_through_governance():
    v = vault()
    out = A2AHandler(v).handle(
        "memory.contribute",
        {"content": "acme moved to enterprise plan", "subject": "customer:acme",
         "attribute": "plan", "value": "enterprise"}, agent="peer")
    assert "id" in out and out["status"] in ("active", "quarantined")


# ---- Integrations --------------------------------------------------------
def test_integrations_catalog():
    cat = catalog()
    ids = {c["id"] for c in cat}
    assert {"slack", "teams", "notion", "jira"} <= ids
    for c in cat:
        assert "live" in c and "token_env" in c


def test_integration_live_reflects_env(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    assert live("slack") is True
    assert live("teams") is False
