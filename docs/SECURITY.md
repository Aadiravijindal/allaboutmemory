# Security model

## Trust boundary: BYOC
The vault runs in the **customer's own cloud**. Memories and encryption keys
never reach our servers. "We can't read your data" is architecture, not a
promise — see `crypto.py::AwsKmsKeyProvider` (keys come from the customer's
KMS; plaintext data keys live only in their tenant memory).

## Memory poisoning (OWASP ASI06) — the headline threat
Attackers plant instructions in an agent's long-term memory via untrusted
ingestion (email, web, uploaded docs) that fire days later. Our defense,
shipped:
- **Provenance on every memory** (`schema.Provenance`) — source + channel +
  trust recorded at write time.
- **The Approval Room** (`store.quarantine_list/approve`) — writes from
  untrusted channels or below the trust threshold are held OUT of the brain
  until a human approves. This is the OWASP-recommended "staging buffer with
  validation," productized.
- **Trust-aware projection** — low-trust and bias-flagged memories are
  excluded from what agents receive (`sync.project`).
- **Undo** — if a poisoned memory slips through, `rollback` / `rollback_since`
  restores the pre-poisoning state.

The demo proves it: the "reroute Acme invoices to account 8841-XX" email is
quarantined and never reaches any AI.

## Tamper evidence
The event log is hash-chained; `Vault.verify_chain()` detects any edit.
Deletion receipts bind to the chain head, so a GDPR erasure is provable and
cannot be silently reversed.

## Access control
- Per-org tenant isolation (separate vault per org).
- RBAC on every API route (`tenancy.ROLE_CAPS`).
- Namespace ACL walls on every read (`policy.allowed_namespaces`).
- Every retrieval logged (the flight recorder) for audit.

## Hardening still to do (see PRODUCTION.md)
- Encrypt the search index too (FTS content is currently searchable
  plaintext inside the tenant DB).
- Signed API requests + rate limiting at the edge.
- Replace the keyword bias/poisoning heuristics with trained classifiers.
- Red-team the injection paths; third-party pen test before GA.
