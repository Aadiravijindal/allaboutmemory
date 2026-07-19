# Feature-by-feature map

Every feature from the product spec, and exactly where it lives in code and
how to see it working.

## PART 1 — THE VAULT

| Feature | Where | See it |
|---|---|---|
| 1.1 One store in THEIR cloud | `store.Vault` (BYOC deploy) | whole vault runs in-process; prod = customer's Postgres |
| 1.2 Every memory carries its "papers" | `schema.Provenance`, `schema.MemoryUnit` | `python mv.py search acme` shows source/trust |
| 1.3 The diary (full history) | `store.Vault.history()` | `python mv.py history <id>` |
| 1.3 The undo button | `store.rollback()`, `rollback_since()` | `python mv.py rollback-since 2026-07-10T00:00:00+00:00` |
| 1.4 Locked with customer's keys | `crypto.Cipher` + KMS `KeyProvider` | `python mv.py --encrypt rescue` |

## PART 2 — THE PLUGS

| Feature | Where | See it |
|---|---|---|
| 2.1 Ready-made connectors | `connectors.FileConnector`, `default_registry()` | reference connectors for 10 platforms |
| 2.2 One door for custom agents (MCP) | `mcp_server.MCPServer` | `memory.search` / `memory.add` over JSON-RPC |
| 2.3 Two-way flow | `Connector.extract()` + `.load()` | rescue pulls; sync projects back |

## PART 3 — THE SYNC ENGINE

| Feature | Where | See it |
|---|---|---|
| 3.1 Automatic daily sync | `sync.SyncEngine.sync_once()` | `python mv.py sync` |
| 3.2 Fight resolution | `store._resolve_conflicts()` | demo: Pro vs Enterprise → newest wins, old kept |
| 3.3 Per-AI diet (projections) | `policy.projection()`, `sync.project()` | support AI gets support+general only |

## PART 4 — THE RESCUE TOOL

| Feature | Where | See it |
|---|---|---|
| 4.1 The extraction | `rescue.RescueTool.run()` | `python mv.py rescue` |
| 4.2 The verification report | `rescue.render_report()` (signed) | printed after every rescue |

## PART 5 — THE CONTROL ROOM

| Feature | Where | See it |
|---|---|---|
| 5.1 Search the AI's brain | `dashboard` `/` | search box |
| 5.2 Fix / delete everywhere | `dashboard` `/delete`, `store.update/delete` | per-memory buttons |
| 5.3 The health score | `insights.health_score()` | header gauge |
| 5.4 The approval room | `store.quarantine_list/approve/reject` | `/approvals` |

## PART 6 — THE RULEBOOK

| Feature | Where | See it |
|---|---|---|
| 6.1 Who-sees-what walls | `policy.allowed_namespaces()` | `search --agent sales_agent` can't see hr |
| 6.2 Auto-expiry rules | `policy.ttl_override_days()` + Cleaner | `policies/default.yaml` |
| 6.3 Delete-with-receipt | `store.delete/erase_subject()` | `python mv.py erase customer:acme` |
| 6.4 The flight recorder | `store._log_retrieval/retrievals()` | `python mv.py why <id>` |

## PART 7 — THE CLEANER

| Feature | Where | See it |
|---|---|---|
| 7.1 Duplicate remover | `cleaner.dedupe()` | `python mv.py clean` |
| 7.2 Freshness keeper | `cleaner.expire_stale()` + `DecayClass` | stale facts retire by class |
| 7.3 Contradiction fixer | `cleaner.resolve_contradictions()` | newest wins, ambiguous → human |
| 7.4 Yes-man filter | `cleaner.flag_bias()` | opinion-shaped memories flagged |

## PART 8 — INSIGHTS

| Feature | Where | See it |
|---|---|---|
| 8.1 What the AI learned | `insights.learned_summary()` | `python mv.py insights` |
| 8.2 Signal alerts | `insights.signal_alerts()` | repeated patterns (e.g. export bug ×3) |
| 8.3 Blind-spot map | `insights.blind_spots()` | stale areas by risk |

## Security properties demonstrated

- **Memory-poisoning defense (OWASP ASI06):** untrusted-channel writes are
  quarantined out of the AI's brain until a human approves (Feature 5.4).
- **Tamper-evidence:** the event log is hash-chained; `Vault.verify_chain()`
  detects any edit. Deletion receipts bind to the chain head (Feature 6.3).
- **Least privilege:** every read passes ACL walls; every retrieval is logged
  (Features 6.1, 6.4).

## NEXT-WAVE ENTERPRISE FEATURES (governance, value, interop)

These extend the 8 core parts with what large buyers ask for in security
reviews and procurement — the difference between a demo and a contract.

| Feature | Where | See it |
|---|---|---|
| Memory ROI (the CFO number) | `roi.ROI.summary()` | `GET /api/roi` · Insights tab |
| Quality evals (reliability scorecard) | `evals.Evals.score()` / `run_eval_set()` | `GET /api/evals` · Insights tab |
| Knowledge graph | `graph.KnowledgeGraph.build()` / `neighborhood()` | `GET /api/graph` · Insights tab |
| Data classification + no-training | `classification.classify()` / `training_allowed()` | set on every write; `restricted` never routes/trains |
| Zero-data-retention (ZDR) | `store.Vault(zero_retention=True)` | env `MV_ZERO_RETENTION` — keep metadata, drop content |
| Real-time write-back | `realtime.RealtimeBus` + `store.event_hook` | `POST /api/realtime/subscribe` — push on every write |
| Consent ledger (GDPR/DPDP) | `consent.ConsentLedger` + `enforce_withdrawals()` | `POST /api/consent/{subject}` — withdraw purges memory |
| A2A protocol (interop) | `a2a.A2AHandler` | `GET /.well-known/agent.json` · `POST /api/a2a/{skill}` |
| Model governance (no silent swaps) | `models.ModelRouter` | `GET /api/models` — pinned set + deprecation notices |
| Workplace integrations | `integrations.catalog()` | `GET /api/integrations` — Slack, Teams, Notion, Jira… |

**Design notes**

- ROI, evals, and the graph are *derived* from the vault's own event log and
  counts — no separate data pipeline, so they're always live.
- Classification runs inside the write path (`store.add`), so every memory
  carries a sensitivity level; `restricted` memory never leaves the tenant.
- Real-time write-back is decoupled: the store fires a plain `event_hook` on
  every committed write, and a misbehaving subscriber can never break a write.
- A2A access is keyed by the caller's **role**, so an agent sees exactly the
  namespaces its role is entitled to — the same ACL walls as the REST API.
