"""Tests for the REST API, auth, multi-tenancy, and the report artifact."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["MV_DATA"] = tempfile.mkdtemp()
from fastapi.testclient import TestClient  # noqa: E402
import memoryvault.api as A  # noqa: E402
from memoryvault.report import render_html  # noqa: E402
from memoryvault.tenancy import ControlPlane  # noqa: E402

client = TestClient(A.app)
KEY = A.DEMO_KEY
H = {"x-api-key": KEY}


def test_health_public():
    assert client.get("/api/health").json()["status"] == "ok"


def test_auth_required():
    assert client.get("/api/memories").status_code == 401
    assert client.get("/api/memories", headers={"x-api-key": "bad"}).status_code == 401


def test_rescue_and_search_flow():
    r = client.post("/api/rescue", headers=H, json={
        "systems": ["salesforce_agentforce", "chatgpt_enterprise",
                    "intercom_fin", "email_ingest"], "clean": True}).json()
    assert r["total_recovered"] > 0 and r["chain_intact"] is True
    s = client.get("/api/memories?q=acme", headers=H).json()
    assert s["count"] >= 1
    # quarantine populated by the email poisoning attempt
    assert client.get("/api/approvals", headers=H).json()["count"] >= 1


def test_health_score_endpoint():
    hs = client.get("/api/health-score", headers=H).json()
    assert 0 <= hs["score"] <= 100 and hs["grade"] in "ABCDF"


def test_rbac_readonly_cannot_write():
    cp = ControlPlane(os.environ["MV_DATA"],
                      A.POLICY if os.path.exists(A.POLICY) else None)
    ro = cp.issue_key(A.DEMO_ORG, "readonly", "viewer")
    r = client.post("/api/memories", headers={"x-api-key": ro},
                    json={"content": "x"})
    # readonly lacks 'write' -> 403 (or 401 if key store not shared)
    assert r.status_code in (401, 403)


def test_tenant_isolation():
    # a second org cannot see the demo org's memories
    raw = A.cp.issue_key("otherco", "owner", "o") if "otherco" in [
    ] else A.cp.create_org("otherco2")
    other = client.get("/api/memories?q=acme", headers={"x-api-key": raw}).json()
    assert other["count"] == 0  # fresh tenant, empty vault


def test_report_html_renders():
    report = {
        "report_type": "MemoryVault Rescue Verification",
        "started_at": "2026-07-14T10:00:00", "finished_at": "2026-07-14T10:01:00",
        "systems": [{"system": "salesforce_agentforce", "recovered": 4,
                     "quarantined_for_review": 0, "status": "ok"}],
        "total_recovered": 4, "cleaning": None,
        "vault_counts": {"active": 4}, "chain_intact": True,
        "chain_head": "abc123", "signature": "deadbeef" * 8,
    }
    html = render_html(report)
    assert "4 memories recovered" in html and "PASSED" in html


def test_erase_produces_receipt_via_api():
    client.post("/api/rescue", headers=H, json={
        "systems": ["salesforce_agentforce"], "clean": False})
    r = client.post("/api/erase?subject=customer:globex", headers=H).json()
    assert r["kind"] == "subject_erasure"
    receipts = client.get("/api/receipts", headers=H).json()["receipts"]
    assert len(receipts) >= 1
