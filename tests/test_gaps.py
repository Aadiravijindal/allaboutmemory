"""Tests for the closed gaps: transform, locker, certification, federation,
sovereign, and (import-only) temporal/sso."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memoryvault.transform import HeuristicTransformer, get_transformer
from memoryvault.locker import LocalLocker
from memoryvault.certification import issue_badge, verify_badge, validate_export
from memoryvault.federation import FederationNetwork, redact, is_shareable
from memoryvault import sovereign
from memoryvault.schema import MemoryUnit, Provenance


# ---- LLM transform layer (heuristic fallback path) -----------------------
def test_transform_infers_structure():
    t = HeuristicTransformer()
    m = t.transform({"content": "Acme is on the Enterprise plan now"},
                    "chatgpt")
    assert m.attribute == "plan" and "enterprise" in m.value.lower()
    assert m.provenance["source_system"] == "chatgpt"


def test_transform_sets_decay():
    t = HeuristicTransformer()
    fast = t.transform({"content": "customer is angry today"}, "x")
    slow = t.transform({"content": "her job title is VP"}, "x")
    assert fast.decay_class == "fast"
    assert slow.decay_class == "slow"


def test_get_transformer_returns_something():
    assert get_transformer() is not None


# ---- S3 evidence locker (local backend) ----------------------------------
def test_locker_stores_and_hashes():
    lk = LocalLocker(tempfile.mkdtemp())
    meta = lk.put("acme", "salesforce", b'{"raw":"data"}')
    assert meta["bytes"] == 14 and len(meta["sha256"]) == 64
    assert lk.get(meta["key"]) == b'{"raw":"data"}'


# ---- certification / portable badge --------------------------------------
def test_certify_pass_and_verify():
    mems = [MemoryUnit(content="x", type="fact",
                       provenance=Provenance(source_system="sf").to_dict()
                       ).to_dict()]
    badge = issue_badge("vendorco", mems)
    assert badge["badge"].startswith("Memory Portable")
    assert verify_badge(badge) is True


def test_certify_fails_without_provenance():
    bad = [{"id": "1", "content": "x", "type": "fact", "provenance": {}}]
    result = validate_export(bad)
    assert result["passed"] is False


# ---- federation network --------------------------------------------------
def test_redaction_strips_pii():
    assert "<email>" in redact("mail me at bob@acme.com please")


def test_only_generalizable_shared():
    customer_mem = {"content": "acme likes evenings", "subject": "customer:acme",
                    "tags": ["shareable"]}
    lesson_mem = {"content": "library X v2 breaks framework Y",
                  "subject": "tech:libx", "tags": ["shareable"]}
    assert is_shareable(customer_mem) is False   # customer data never shared
    assert is_shareable(lesson_mem) is True


def test_federation_contribute_and_query():
    net = FederationNetwork(os.path.join(tempfile.mkdtemp(), "fed.jsonl"))
    r = net.contribute("acme", [
        {"content": "API rate limits silently at 100 rps",
         "subject": "tech:api", "tags": ["shareable"]}])
    assert r["shared"] == 1 and r["credits_earned"] == 1
    hits = net.query("rate limits")
    assert len(hits) >= 1


# ---- sovereign editions --------------------------------------------------
def test_sovereign_profiles():
    os.environ["MV_SOVEREIGN"] = "eu"
    # reload module-level read
    import importlib
    importlib.reload(sovereign)
    assert sovereign.active_profile().residency_required is True
    assert sovereign.region_allowed("eu-west-1") is True
    assert sovereign.region_allowed("us-east-1") is False
    os.environ["MV_SOVEREIGN"] = "gov"
    importlib.reload(sovereign)
    assert sovereign.federation_allowed() is False
    os.environ.pop("MV_SOVEREIGN", None)
    importlib.reload(sovereign)


# ---- temporal + sso import cleanly (no cluster/keys needed) ---------------
def test_optional_modules_import():
    from memoryvault import temporal_workflows, sso
    assert temporal_workflows.temporal_enabled() in (True, False)
    assert sso.sso_enabled() in (True, False)
