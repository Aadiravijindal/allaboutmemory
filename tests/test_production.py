"""Tests for the config-driven production layer: activation, durable sync,
billing meter, live-connector registration."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memoryvault import Vault, Policy, default_registry
from memoryvault.durable import DurableSync
from memoryvault.billing import Meter
from memoryvault.config import Config

FIX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "fixtures")
POL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "policies", "default.yaml")


def fresh_vault():
    return Vault(os.path.join(tempfile.mkdtemp(), "v.db"), policy=Policy.load(POL))


# ---- durable sync ---------------------------------------------------------
def test_durable_runs_and_completes():
    v = fresh_vault()
    reg = default_registry(FIX)
    reg.connect("salesforce_agentforce")
    ds = DurableSync(v, reg)
    ds.enqueue("full")
    res = ds.run_due()
    assert res["done"] == 1 and res["deadlettered"] == 0


def test_durable_retries_then_deadletters():
    v = fresh_vault()
    reg = default_registry(FIX)
    ds = DurableSync(v, reg, max_attempts=2, base_backoff=0)
    # a job whose kind is invalid always fails -> retry -> deadletter
    ds.enqueue("bogus_kind")
    ds.run_due()   # attempt 1 -> retry
    ds.run_due()   # attempt 2 -> deadletter
    assert len(ds.deadletters()) == 1
    assert ds.stats().get("dead") == 1


# ---- billing meter --------------------------------------------------------
def test_meter_summary():
    m = Meter(tempfile.mkdtemp())
    m.record("acme", "rescue")
    m.record("acme", "connector_active", 2)
    s = m.summary("acme")
    assert s["events"]["rescue"] == 1
    assert s["events"]["connector_active"] == 2
    assert s["estimated_usd"] == 2 * 500 + 1 * 15000


# ---- config activation ----------------------------------------------------
def test_config_activation_defaults_demo():
    c = Config(database_url="", encrypt=False, stripe_secret_key="")
    a = c.activated()
    assert a["storage"].startswith("sqlite")
    assert a["billing"] == "off (demo)"
    assert a["connectors_live"] == []


def test_config_activation_with_keys():
    c = Config(database_url="postgres://x", encrypt=True,
               stripe_secret_key="sk_test", mem0_api_key="k",
               salesforce_token="t")
    a = c.activated()
    assert a["storage"] == "postgres"
    assert a["billing"] == "stripe"
    assert "mem0" in a["connectors_live"]
    assert "salesforce" in a["connectors_live"]


# ---- live connector registration ------------------------------------------
def test_live_connector_registration(monkeypatch=None):
    # simulate a pasted key by editing CONFIG at runtime
    from memoryvault import connectors_live as CL
    CL.CONFIG.mem0_api_key = "test_key"
    try:
        assert "mem0" in CL.live_systems()
        reg = default_registry(FIX)
        CL.register_live(reg)
        conn = reg.connect("mem0")
        assert type(conn).__name__ == "Mem0Connector"
    finally:
        CL.CONFIG.mem0_api_key = ""
