"""The MemoryVault REST API — the real product interface.

FastAPI app exposing every part of the product over HTTP, with:
  - API-key auth + per-org multi-tenant isolation + RBAC (tenancy.py)
  - structured request logging + a health endpoint
  - auto-generated OpenAPI docs at /api/docs
  - serves the Control Room SPA at /

Run:  uvicorn memoryvault.api:app --reload      (or: python -m memoryvault.api)
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request, Depends
from fastapi.responses import JSONResponse, HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from .tenancy import ControlPlane
from .schema import MemoryUnit, Provenance
from .cleaner import Cleaner
from .insights import Insights
from .rescue import RescueTool
from .sync import SyncEngine
from .connectors import default_registry
from .connectors_live import register_live, live_systems
from .config import CONFIG
from .billing import Meter, StripeBilling
from .durable import DurableSync

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s %(message)s')
log = logging.getLogger("memoryvault.api")

DATA_DIR = os.environ.get("MV_DATA", "data")
FIXTURES = os.environ.get("MV_FIXTURES",
                          os.path.join(os.path.dirname(__file__), "..",
                                       "fixtures"))
POLICY = os.path.join(os.path.dirname(__file__), "..", "policies",
                      "default.yaml")

cp = ControlPlane(DATA_DIR, POLICY if os.path.exists(POLICY) else None)

# bootstrap a demo org so the API/dashboard work out of the box
DEMO_ORG = os.environ.get("MV_DEMO_ORG", "demo")
_demo_key_file = os.path.join(DATA_DIR, "demo_key.txt")
if not os.path.exists(_demo_key_file):
    _k = cp.create_org(DEMO_ORG, "demo-owner")
    with open(_demo_key_file, "w") as f:
        f.write(_k)
    log.info("Bootstrapped demo org. API key written to %s", _demo_key_file)
with open(_demo_key_file) as f:
    DEMO_KEY = f.read().strip()

app = FastAPI(title="MemoryVault API", version="0.3.0",
              docs_url="/api/docs", openapi_url="/api/openapi.json")

meter = Meter(DATA_DIR)
billing = StripeBilling()


def build_registry():
    """Demo FileConnectors, overlaid with any live connectors whose keys
    are pasted in .env. Paste a key -> that platform goes live here."""
    reg = default_registry(os.path.abspath(FIXTURES))
    register_live(reg)
    return reg


# ------------------------------------------------------------------ auth
async def auth(x_api_key: Optional[str] = Header(None),
               authorization: Optional[str] = Header(None)):
    raw = x_api_key
    if not raw and authorization and authorization.lower().startswith("bearer "):
        raw = authorization[7:]
    key = cp.resolve(raw)
    if not key:
        raise HTTPException(401, "missing or invalid API key")
    return key


def require(cap: str):
    async def dep(key=Depends(auth)):
        if not cp.can(key.role, cap):
            raise HTTPException(403, f"role '{key.role}' lacks '{cap}'")
        return key
    return dep


@app.middleware("http")
async def log_requests(request: Request, call_next):
    t0 = time.time()
    resp = await call_next(request)
    log.info("%s %s -> %s (%.0fms)", request.method, request.url.path,
             resp.status_code, (time.time() - t0) * 1000)
    return resp


# --------------------------------------------------------------- models
class MemoryIn(BaseModel):
    content: str
    subject: str = ""
    attribute: str = ""
    value: str = ""
    namespace: str = "general"
    type: str = "fact"
    source_system: str = "api"
    channel: str = "api"
    trust: float = 0.6
    tags: list = []


class RescueIn(BaseModel):
    systems: list
    clean: bool = True


# ---------------------------------------------------------------- routes
@app.get("/api/health")
async def health():
    return {"status": "ok", "version": app.version, "orgs": len(cp._vaults)}


@app.get("/api/me")
async def me(key=Depends(auth)):
    return {"org": key.org, "role": key.role, "name": key.name}


@app.get("/api/memories")
async def search(q: str = "", agent: str = "admin", limit: int = 50,
                 status: str = "active", key=Depends(require("read"))):
    v = cp.vault_for(key.org)
    hits = v.search(query=q, agent=agent, limit=limit, status=status,
                    context=f"api:{key.name or key.role}")
    return {"count": len(hits), "memories": [m.to_dict() for m in hits]}


@app.post("/api/memories")
async def add(m: MemoryIn, key=Depends(require("write"))):
    v = cp.vault_for(key.org)
    prov = Provenance(source_system=m.source_system, channel=m.channel,
                      agent_id=key.name or key.role)
    unit = MemoryUnit(content=m.content, subject=m.subject,
                      attribute=m.attribute, value=m.value,
                      namespace=m.namespace, type=m.type, trust=m.trust,
                      tags=m.tags, provenance=prov.to_dict())
    saved = v.add(unit, actor=f"api:{key.name or key.role}")
    return {"id": saved.id, "status": saved.status}


@app.get("/api/memories/{mid}")
async def get_one(mid: str, key=Depends(require("read"))):
    m = cp.vault_for(key.org).get(mid)
    if not m:
        raise HTTPException(404, "not found")
    return m.to_dict()


@app.get("/api/memories/{mid}/history")
async def history(mid: str, key=Depends(require("read"))):
    return {"history": cp.vault_for(key.org).history(mid)}


@app.post("/api/memories/{mid}/rollback")
async def rollback(mid: str, seq: int, key=Depends(require("write"))):
    m = cp.vault_for(key.org).rollback(mid, seq, actor=f"api:{key.role}")
    return {"ok": bool(m), "value": m.value if m else None}


@app.delete("/api/memories/{mid}")
async def delete(mid: str, key=Depends(require("delete"))):
    r = cp.vault_for(key.org).delete(mid, actor=f"api:{key.role}")
    cp.audit(key.org, key.name or key.role, "delete_memory", {"id": mid})
    return r or {"ok": False}


@app.get("/api/memories/{mid}/why")
async def why(mid: str, key=Depends(require("read"))):
    return {"retrievals": cp.vault_for(key.org).retrievals(memory_id=mid)}


@app.post("/api/erase")
async def erase(subject: str, key=Depends(require("delete"))):
    r = cp.vault_for(key.org).erase_subject(subject, actor=f"api:{key.role}")
    cp.audit(key.org, key.name or key.role, "erase_subject", {"subject": subject})
    return r


# ---- Approval Room ----------------------------------------------------
@app.get("/api/approvals")
async def approvals(key=Depends(require("read"))):
    q = cp.vault_for(key.org).quarantine_list()
    return {"count": len(q), "memories": [m.to_dict() for m in q]}


@app.post("/api/approvals/{mid}/approve")
async def approve(mid: str, key=Depends(require("approve"))):
    m = cp.vault_for(key.org).approve(mid, actor=f"api:{key.role}")
    return {"ok": bool(m)}


@app.post("/api/approvals/{mid}/reject")
async def reject(mid: str, key=Depends(require("approve"))):
    m = cp.vault_for(key.org).reject(mid, actor=f"api:{key.role}")
    return {"ok": bool(m)}


# ---- engine operations ------------------------------------------------
@app.post("/api/rescue")
async def rescue(body: RescueIn, key=Depends(require("connect"))):
    v = cp.vault_for(key.org)
    report = RescueTool(v, build_registry()).run(body.systems, clean=body.clean)
    meter.record(key.org, "rescue", meta={"systems": body.systems})
    cp.audit(key.org, key.name or key.role, "rescue",
             {"systems": body.systems, "recovered": report["total_recovered"]})
    return report


@app.post("/api/rescue/report", response_class=HTMLResponse)
async def rescue_report(body: RescueIn, key=Depends(require("connect"))):
    """Run a rescue and return the verification report as printable HTML."""
    from .report import render_html
    v = cp.vault_for(key.org)
    report = RescueTool(v, build_registry()).run(body.systems, clean=body.clean)
    return render_html(report)


@app.post("/api/sync")
async def sync(key=Depends(require("connect"))):
    v = cp.vault_for(key.org)
    reg = build_registry()
    for s in reg.available():
        try:
            reg.connect(s)
            meter.record(key.org, "connector_active", meta={"system": s})
        except Exception:
            pass
    return SyncEngine(v, reg).sync_once()


@app.post("/api/clean")
async def clean(key=Depends(require("write"))):
    return Cleaner(cp.vault_for(key.org)).run_all()


# ---- insights ---------------------------------------------------------
@app.get("/api/health-score")
async def health_score(key=Depends(require("read"))):
    return Insights(cp.vault_for(key.org)).health_score()


@app.get("/api/insights")
async def insights(days: int = 180, key=Depends(require("read"))):
    ins = Insights(cp.vault_for(key.org))
    return {"learned": ins.learned_summary(days=days),
            "signals": ins.signal_alerts(min_count=2),
            "blind_spots": ins.blind_spots()}


@app.get("/api/receipts")
async def receipts(key=Depends(require("read"))):
    return {"receipts": cp.vault_for(key.org).receipts_list()}


@app.get("/api/verify-chain")
async def verify_chain(key=Depends(require("read"))):
    return {"intact": cp.vault_for(key.org).verify_chain()}


@app.get("/api/counts")
async def counts(key=Depends(require("read"))):
    return cp.vault_for(key.org).counts()


# ---- setup / status (what's activated by your keys) ------------------
@app.get("/api/setup")
async def setup_status(key=Depends(require("admin"))):
    from .sso import sso_enabled
    from .sovereign import status as sov_status
    from .temporal_workflows import temporal_enabled
    act = CONFIG.activated()
    act["live_connectors"] = live_systems()
    act["billing_ledger"] = meter.summary(key.org)
    act["sso"] = "workos" if sso_enabled() else "api-key (demo)"
    act["sync_runtime"] = "temporal" if temporal_enabled() else "durable-queue"
    act["sovereign"] = sov_status()
    return act


# ---- SSO (WorkOS) -----------------------------------------------------
@app.get("/auth/login")
async def auth_login():
    from .sso import authorization_url, sso_enabled
    import secrets as _s
    if not sso_enabled():
        raise HTTPException(400, "SSO not configured (set WORKOS_API_KEY)")
    return {"authorization_url": authorization_url(_s.token_urlsafe(8))}


@app.get("/auth/callback")
async def auth_callback(code: str):
    from .sso import complete_login, SESSIONS
    profile = complete_login(code)
    cp.create_org(profile["org"]) if profile["org"] not in cp._vaults else None
    sid = SESSIONS.create(profile["org"], profile["email"], profile["role"])
    return {"session": sid, "org": profile["org"], "email": profile["email"]}


# ---- certification: Portable-✓ badge ---------------------------------
@app.post("/api/certify")
async def certify(key=Depends(require("read"))):
    from .certification import issue_badge
    v = cp.vault_for(key.org)
    mems = [m.to_dict() for m in v.all_memories(status="active")]
    return issue_badge(key.org, mems)


# ---- federation: opt-in shared knowledge network ---------------------
@app.post("/api/federation/contribute")
async def fed_contribute(key=Depends(require("admin"))):
    from .federation import FederationNetwork
    from .sovereign import federation_allowed
    if not federation_allowed():
        raise HTTPException(403, "federation disabled for this sovereign edition")
    v = cp.vault_for(key.org)
    net = FederationNetwork(os.path.join(DATA_DIR, "federation.jsonl"))
    mems = [m.to_dict() for m in v.all_memories(status="active")]
    return net.contribute(key.org, mems)


@app.get("/api/federation/query")
async def fed_query(q: str, key=Depends(require("read"))):
    from .federation import FederationNetwork
    net = FederationNetwork(os.path.join(DATA_DIR, "federation.jsonl"))
    return {"lessons": net.query(q)}


# ---- sovereign edition status ----------------------------------------
@app.get("/api/sovereign")
async def sovereign(key=Depends(require("read"))):
    from .sovereign import status
    return status()


# ---- React dashboard (alt UI) ----------------------------------------
@app.get("/react", response_class=HTMLResponse)
async def react_ui():
    ui = os.path.join(os.path.dirname(__file__), "..", "web", "react",
                      "index.html")
    if os.path.exists(ui):
        with open(ui) as f:
            return f.read()
    raise HTTPException(404, "react UI not found")


# ---- billing ----------------------------------------------------------
@app.get("/api/billing/usage")
async def billing_usage(key=Depends(require("admin"))):
    return meter.summary(key.org)


@app.post("/api/billing/webhook")
async def billing_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = billing.verify_webhook(payload, sig)
        if event:
            log.info("stripe event: %s", event.get("type"))
        return {"received": True}
    except Exception as e:
        raise HTTPException(400, f"webhook error: {e}")


# ---- durable sync (retries / dead-letter) -----------------------------
@app.post("/api/durable/enqueue")
async def durable_enqueue(kind: str = "full", key=Depends(require("connect"))):
    ds = DurableSync(cp.vault_for(key.org), build_registry())
    ds.enqueue(kind)
    return ds.run_due()


@app.get("/api/durable/stats")
async def durable_stats(key=Depends(require("read"))):
    ds = DurableSync(cp.vault_for(key.org), build_registry())
    return {"jobs": ds.stats(), "deadletters": ds.deadletters()}


# ---- serve the Control Room SPA + expose demo key for the UI ----------
@app.get("/api/demo-key", response_class=PlainTextResponse)
async def demo_key():
    """Convenience for the bundled demo UI only."""
    return DEMO_KEY


@app.get("/", response_class=HTMLResponse)
async def spa():
    ui = os.path.join(os.path.dirname(__file__), "..", "web", "index.html")
    if os.path.exists(ui):
        with open(ui) as f:
            return f.read()
    return "<h1>MemoryVault API</h1><p>See /api/docs</p>"


def main():  # pragma: no cover
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))


if __name__ == "__main__":  # pragma: no cover
    main()
