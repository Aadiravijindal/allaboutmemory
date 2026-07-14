# The Canonical Memory Interchange Format (CMIF) v0.1

**An open spec for portable AI memory.** This is the standards land-grab:
if the ecosystem adopts CMIF as the format memory travels in, MemoryVault
owns the memory layer of the agent stack the way MCP owns tools.

Published openly on purpose. Vendors, engines, and agents are invited to
read and write CMIF.

## A memory unit

```json
{
  "id": "hex-uuid",
  "content": "Acme Corp prefers evening calls after 5pm ET",
  "type": "fact | preference | episode | procedure | opinion",
  "namespace": "sales",
  "subject": "customer:acme",
  "attribute": "call_time",
  "value": "evening",
  "entities": ["Acme Corp"],
  "tags": ["contact"],
  "trust": 0.8,
  "status": "active | quarantined | superseded | expired | deleted",
  "decay_class": "permanent | slow | medium | fast",
  "occurred_at": "2026-03-03T18:00:00+00:00",
  "ingested_at": "2026-07-14T10:00:00+00:00",
  "expires_at": "2026-06-01T18:00:00+00:00",
  "provenance": {
    "source_system": "salesforce_agentforce",
    "agent_id": "sdr-bot-3",
    "channel": "call",
    "author": "",
    "occurred_at": "2026-03-03T18:00:00+00:00"
  },
  "version": 1,
  "supersedes": null,
  "bias_risk": false
}
```

## Field semantics (the parts that make it more than JSON)

- **provenance** — the "papers". Every memory records where it came from,
  which agent wrote it, and through which channel. This is what makes trust
  scoring, poisoning defense, and audit possible. A CMIF memory without
  provenance is untrusted by default.
- **subject + attribute + value** — the canonical claim. Two memories with
  the same canonicalized `subject`+`attribute` but different `value`
  *conflict*; resolution is by per-attribute policy (recency vs trust).
  Entity resolution folds `Acme` / `Acme Corp` to one subject.
- **decay_class** — how fast the fact ages. Producers SHOULD set it; the
  default is `medium`. This drives automatic forgetting.
- **status** — lifecycle. `quarantined` means "not yet trusted into the
  brain" (poisoning defense). `superseded` / `expired` are kept for history,
  never deleted, so the diary and undo work.
- **trust** — 0..1 confidence in the source. Untrusted channels (email, web,
  upload) start low and are quarantined until reviewed.

## Portability guarantees

1. Any CMIF store MUST be able to export and import the full document.
2. Losing `provenance` on transfer is a compliance downgrade and MUST be
   reported (the verification report names it).
3. History (the event log) is exportable as an append-only list of
   `{ts, actor, action, memory_id, snapshot}` records, hash-chained.

## Transport

CMIF rides existing rails:
- **MCP** — a CMIF memory server exposes `memory.search` / `memory.add`.
- **A2A** — agents exchange CMIF units directly.
- **REST** — the MemoryVault API is a reference CMIF endpoint.

## Reference implementation

`memoryvault/schema.py` is the normative reference for v0.1.
