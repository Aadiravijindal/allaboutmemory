# Architecture

## The big picture

```
        THEIR CLOUD (customer's AWS / Azure / GCP account)
┌──────────────────────────────────────────────────────────────┐
│                                                                │
│   CONNECTORS ──► SYNC ENGINE ──► THE VAULT                     │
│   (Part 2)        (Part 3)       (Part 1: Postgres+pgvector    │
│    extract/load    pull+project    + event log + object store) │
│        │              │                 │                       │
│        │              │                 ▼                       │
│        │              │            POLICY ENGINE (Part 6)       │
│        │              │            CLEANER WORKERS (Part 7)     │
│        │              ▼                 │                       │
│        │        PROJECTION PROFILES     ▼                       │
│        └──────► (per-AI diet)      CONTROL ROOM (Part 5)        │
│                                    INSIGHTS (Part 8)            │
└──────────────────────────────────────────────────────────────┘
   OUR CLOUD: licensing, connector definitions, updates only —
   never the customer's memories.
```

**Deployment model: BYOC ("bring your own cloud").** We ship software (Docker
+ Helm + Terraform) that installs into the *customer's* account. Their data
never touches our servers. That is what makes "we can't read it" literally
true, and it's why regulated buyers (banks, hospitals, government) can adopt.

## The one design decision that powers half the product

**Event sourcing.** Nothing is ever overwritten. Every change appends an
event carrying a full snapshot, hash-chained to the previous event. From that
single decision we get, for free:

- **1.3 the diary** — the event log *is* the history
- **the undo button** — restore any past snapshot
- **6.4 the flight recorder** — retrievals are events too
- **6.3 tamper-proof receipts** — the hash chain detects any edit
- **auditability** — "what did the AI believe in April?" is one query

`Vault.verify_chain()` walks the chain and returns `False` if any event was
altered — see `tests/test_product.py::test_chain_tamper_evident`.

## The canonical schema is the crown jewel

`schema.MemoryUnit` is the interchange format. Every connector translates a
vendor's messy records *into* it; every projection translates *out* of it.
If this format becomes the standard the ecosystem adopts (the way MCP became
the standard for tools), we own the memory layer of the stack.

Key fields: `content`, `type`, `namespace` (ACL wall), `subject`+`attribute`+
`value` (for conflict detection), `provenance` (the "papers"), `trust`,
`status`, `decay_class` (aging speed), `expires_at`, and a `version`/
`supersedes` history pointer.

## Conflict resolution (Feature 3.2)

When two AIs learn different values for the same `subject`+`attribute`:
**newest wins**, trust breaks same-time ties, and the loser becomes
`superseded` (kept in history, never lost). Recency dominates because these
are mutable facts — a plan upgrade or an address change is *newer truth*, and
a high-trust old memory must not block updates forever. Low-trust or
untrusted-channel writes never reach this stage — the Approval Room gates
them first.

## Demo → production mapping

| Concern | This repo (runs anywhere) | Production |
|---|---|---|
| Store | SQLite + FTS5 | Postgres + pgvector, customer cloud |
| Vectors/search | FTS5 + LIKE fallback | pgvector semantic + BM25 + entity boost |
| Keys | local key file | customer KMS (envelope encryption) |
| Connectors | `FileConnector` over JSON | vendor APIs / exports / Data-Act channels |
| Sync | in-process loop | Temporal workflows |
| Cleaner | synchronous pass | nightly job queue + embeddings/LLM |
| Transform | pass-through | in-tenant LLM (Bedrock/Azure OpenAI) |
| Dashboard | Flask, no auth | same UI + SSO (WorkOS), RBAC |

The **interfaces never change** — only the drivers behind them.

## Module layout

```
memoryvault/
  schema.py      Part 1  canonical memory format + provenance + decay
  crypto.py      Part 1  envelope encryption (KMS interface)
  store.py       Part 1  the event-sourced vault (+ enforces Part 6)
  connectors.py  Part 2  the plugs + registry ("click to connect X")
  mcp_server.py  Part 2  MCP door for custom agents
  sync.py        Part 3  pull + project + per-AI diet
  rescue.py      Part 4  extraction + signed verification report
  policy.py      Part 6  the Rulebook (quarantine, ACL, TTL, projections)
  cleaner.py     Part 7  dedupe, freshness, contradictions, yes-man filter
  insights.py    Part 8  health score, learned summary, signals, blind spots
dashboard.py     Part 5  the Control Room web app
mv.py            CLI over every part
demo.py          end-to-end story on sample data
```
