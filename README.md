# 🧠 MemoryVault

**One memory your company owns, that every AI plugs into.**

Every AI a company uses — Microsoft Copilot, Salesforce Agentforce, ChatGPT
Enterprise, Claude, support bots — learns things every day: customer facts,
decisions, what works, what fails. Today that knowledge is **trapped inside
each vendor's walls**, doesn't talk between tools, and dies when a contract
ends. MemoryVault gives the company **one memory it owns**, in its own cloud,
that every AI reads from and writes back to — so the knowledge compounds
forever and no vendor can hold it hostage.

> The AI platforms become replaceable screens you plug into your memory.
> The memory is the computer.

This repo is a **working reference implementation** of the whole product —
all 8 parts, runnable today.

---

## Quick start (30 seconds)

```bash
pip install -r requirements.txt

# ── the real product: API + beautiful Control Room ──
uvicorn memoryvault.api:app --port 8000
#   open http://localhost:8000  →  click "Run Rescue"  →  watch it work
#   API docs at http://localhost:8000/api/docs

# ── or one command with Docker (API + Postgres) ──
docker compose up

# ── the terminal walkthrough of all 8 parts ──
python demo.py

# ── tests (20: engine + API) ──
python -m pytest tests/ -q
```

**The 60-second "wow":** open the Control Room, hit **Run Rescue** — you
watch 13 memories pulled from four platforms, a memory-poisoning email
caught and quarantined, a plan conflict resolved (newest wins, old kept in
history), a live health score, and a tamper-check pass. One screen. Seconds.

---

## The 8 parts → the code

| Part | What it is | Module |
|------|-----------|--------|
| **1. The Vault** | one owned, event-sourced store with provenance, history/undo, encryption | `memoryvault/store.py`, `schema.py`, `crypto.py` |
| **2. The Plugs** | connectors for every platform + an MCP door for custom agents | `memoryvault/connectors.py`, `mcp_server.py` |
| **3. The Sync Engine** | one brain many hands: pull + project, conflict resolution, per-AI diet | `memoryvault/sync.py` |
| **4. The Rescue Tool** | day-one extraction + signed verification report | `memoryvault/rescue.py` |
| **5. The Control Room** | search / fix / delete / approve, health score | `dashboard.py` |
| **6. The Rulebook** | who-sees-what walls, auto-expiry, delete-with-receipt, flight recorder | `memoryvault/policy.py` (+ enforced in `store.py`) |
| **7. The Cleaner** | dedupe, freshness, contradiction fixer, yes-man filter | `memoryvault/cleaner.py` |
| **8. Insights** | what the AI learned, signal alerts, blind-spot map | `memoryvault/insights.py` |

Every feature from the product spec maps to real code — see
[`docs/FEATURES.md`](docs/FEATURES.md) for the feature-by-feature map, and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for how it's built.

### What makes this industry-grade (not just a demo)

| Layer | Built | Where |
|---|---|---|
| REST API (FastAPI) + OpenAPI + logging + health | ✅ | `memoryvault/api.py` |
| API-key auth + multi-tenant isolation + RBAC + audit | ✅ | `memoryvault/tenancy.py` |
| Beautiful Control Room SPA | ✅ | `web/index.html` |
| Entity resolution + embedding dedupe + per-attribute conflict | ✅ | `entities.py`, `embeddings.py` |
| Live connector contracts (Mem0, ChatGPT export, REST, Data-Act) | ✅ | `connectors_live.py` |
| Postgres + pgvector backend | 🔌 wired | `postgres.py` |
| AWS KMS envelope encryption | 🔌 wired | `crypto.py` |
| Python SDK, Docker, docker-compose, CI | ✅ | `sdk/`, `Dockerfile`, `.github/` |
| Open interchange spec (CMIF) | ✅ | `docs/SPEC.md` |
| SOC 2, pen test, live vendor creds, BYOC apply | 🧑‍💼 needs you | `docs/PRODUCTION.md` |

### Going live is "paste keys"

Everything that can be code is done and **config-driven**. Copy
`.env.example` → `.env`, paste credentials, and each integration activates
automatically — no code change:

```bash
cp .env.example .env       # paste keys
python setup_check.py       # shows exactly what activated
```

| Paste this | Activates |
|---|---|
| `DATABASE_URL` | Postgres + pgvector backend |
| `MV_KMS_KEY_ID` | customer-KMS encryption |
| `MEM0_API_KEY` / `SALESFORCE_TOKEN` / … | that live connector |
| `OPENAI_API_KEY` | real embeddings |
| `STRIPE_SECRET_KEY` | real billing |

Deploy into your own cloud with one command (`deploy/terraform` or
`deploy/helm`). Durable sync (retries + dead-letter) is built in.

See **[`GO_LIVE.md`](GO_LIVE.md)** for the full paste-and-run checklist,
[`docs/PRODUCTION.md`](docs/PRODUCTION.md) for the done/wired/needs-you
breakdown, [`docs/SECURITY.md`](docs/SECURITY.md) for the security model,
`compliance/` for the SOC 2 control mapping, `legal/` for DPA/ToS/Data-Act
templates, and [`docs/BUSINESS.md`](docs/BUSINESS.md) for market, moat, and
the expansion plan.

**The only things left are the human half** — the SOC 2 *audit*, a pen test,
a lawyer signing the DPA, and your first customers. We've shipped every
artifact those need (`compliance/`, `legal/`); only the signature remains.

---

## Why this is a company, not a feature

- **It's a system of record.** AI memory — what a company's AI collectively
  knows — is the newest system of record, and nobody owns it. Every vendor is
  *disqualified* from building it: Microsoft won't build the thing that makes
  Microsoft replaceable. Only a neutral outsider can.
- **The law forces the doors open.** The EU Data Act (in force since Sept
  2025) requires vendors to hand over customer data in machine-readable form
  and cooperate with the receiving provider — the extraction crowbar.
- **The moat compounds:** connector edge-cases → the canonical format → live
  sync that's un-removable → the standard everyone certifies against.

See [`docs/BUSINESS.md`](docs/BUSINESS.md) for the market, competitors, moat,
and the Move → Sync → Services → Standard → Network expansion plan.

---

## How the demo maps to production

This implementation runs on **SQLite + local files** so it works with zero
setup. The code is structured so production is a driver swap, not a rewrite:

| Demo | Production |
|------|-----------|
| SQLite | Postgres + pgvector, in the customer's own cloud (BYOC) |
| local key file | the customer's KMS (AWS/Azure/GCP) — keys never leave their account |
| `FileConnector` over JSON fixtures | real vendor APIs / exports / EU-Data-Act channels |
| in-process sync loop | Temporal workflows (retries, rate-limits, resumability) |
| Flask dashboard | same UI, hardened + SSO |

Nothing about the architecture changes — only the drivers behind the same
interfaces.
