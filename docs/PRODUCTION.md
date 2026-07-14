# From this repo to production — the honest checklist

This repo is a **fully working product on SQLite + local files** so anyone
can run it in 30 seconds. Below is exactly what turns it into an
enterprise-grade, sellable system: what's already **done**, what's **wired**
(interface built, needs external creds/infra), and what needs **you** (people,
money, time — no code can do it).

## ✅ DONE (runs and is tested here)
- All 8 product parts, end to end (see `docs/FEATURES.md`)
- REST API (FastAPI) + OpenAPI docs, structured logging, health endpoint
- API-key auth + per-org multi-tenant isolation + RBAC + admin audit log
- Beautiful Control Room SPA (search, approvals, insights, receipts, history)
- Smarter engine: entity resolution, embedding-based dedupe, per-attribute
  conflict policy, pluggable embeddings
- Verification report as printable HTML artifact
- Tamper-evident hash-chained event log + delete-with-receipt
- Python SDK, Docker, docker-compose, GitHub Actions CI, 20 tests
- The open interchange spec (CMIF, `docs/SPEC.md`)

## 🔌 WIRED (interface built — plug in creds/infra to go live)
| Piece | Where | What's needed |
|---|---|---|
| Postgres + pgvector backend | `memoryvault/postgres.py` | a live PG w/ pgvector; port the SQL from `store.py` (mechanical) + run `DATABASE_URL` |
| AWS KMS encryption | `memoryvault/crypto.py::AwsKmsKeyProvider` | customer AWS account + CMK; `pip install boto3` |
| Real embeddings | `memoryvault/embeddings.py::OpenAIEmbedder` | OpenAI/Bedrock key (runs in-tenant) |
| Live connectors | `memoryvault/connectors_live.py` | **vendor credentials** (your Salesforce org, Mem0 key, ChatGPT Enterprise compliance export) |
| Docker Compose w/ Postgres | `docker-compose.yml` | `docker compose up` |

## 🧑‍💼 NEEDS YOU (no code substitutes for these)
| Item | Who does it | Time |
|---|---|---|
| **Real connectors, hardened** | eng, against live vendor tenants — *the moat* | weeks each |
| **SOC 2 Type II** | Vanta/Drata + an auditor | ~6 months (start now) |
| **Penetration test** | a security firm | weeks |
| **BYOC deploy, applied** | Terraform/Helm run in a customer cloud | per-customer |
| **Temporal for durable sync** | eng (interface is the sync engine already) | weeks |
| **3 design-partner customers** | you — the only real validation | ongoing |
| **Legal** (entity, DPAs, ToS, Data-Act playbook) | a lawyer | weeks |
| **Billing / usage metering** | Stripe integration | days–weeks |

## The "minimum sellable" milestone
In priority order, this is what unlocks the first paid pilot:
1. **Two real, hardened connectors** (e.g. Mem0↔vault + ChatGPT Enterprise
   export) — turns the demo into "watch me move your real memory."
2. **Postgres backend + AWS KMS** wired to one customer cloud (BYOC).
3. **SOC 2 started** (runs in parallel — begin immediately).
4. **One design partner** doing a paid rescue.

Everything else (Temporal, billing, the marketplace, the network) comes
after the first "yes." Realistic: **3–6 months with a small strong team**,
and the connectors are the long pole.

## Why the demo already impresses
Open `/`, click **Run Rescue**: you watch 13 memories pulled from four
"platforms", a memory-poisoning email caught and quarantined, a plan
conflict resolved (newest wins, old kept in history), health scored, and a
tamper-check pass — in one screen, in seconds. That is the "this is the next
big thing" moment; the production checklist above is what makes it a company.
