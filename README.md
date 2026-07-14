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

## Quick start

```bash
pip install -r requirements.txt

# PART 4 — rescue trapped memory out of every platform into your vault
python mv.py rescue

# see the whole product story end-to-end
python demo.py

# PART 5 — open the Control Room (web dashboard)
python dashboard.py         # http://localhost:5000

# run the tests (all 8 parts)
python -m pytest tests/ -q
```

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
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for how it's built and how the
demo maps to production (Postgres, Temporal, BYOC, KMS).

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
