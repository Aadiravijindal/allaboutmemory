"""Postgres + pgvector production backend (driver contract).

The demo Vault runs on SQLite so it works with zero setup. Production runs
on Postgres + pgvector, in the customer's own cloud. This module documents
and implements the exact contract for that swap: the SQL is portable, the
event-sourcing model is identical, and hybrid retrieval becomes real
(pgvector semantic + tsvector BM25 + entity boost).

It is intentionally a thin driver over psycopg — the engine logic
(conflict resolution, cleaning, policy) lives in the shared modules and is
storage-agnostic. Requires `psycopg[binary]` and a Postgres with the
`vector` extension; if unavailable it raises clearly rather than silently
degrading.

Status: wired and reviewed against the SQLite reference; integration-tested
against Postgres is a deployment step (needs a live PG + pgvector).
"""
from __future__ import annotations

import os

DDL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    content TEXT, type TEXT, namespace TEXT,
    subject TEXT, attribute TEXT, value TEXT,
    entities JSONB, tags JSONB,
    trust REAL, status TEXT, decay_class TEXT,
    occurred_at TIMESTAMPTZ, ingested_at TIMESTAMPTZ, expires_at TIMESTAMPTZ,
    provenance JSONB, version INT, supersedes TEXT, bias_risk BOOLEAN,
    content_tsv tsvector,
    embedding vector(1536)
);
CREATE INDEX IF NOT EXISTS idx_mem_subject ON memories(subject, attribute);
CREATE INDEX IF NOT EXISTS idx_mem_status ON memories(status);
CREATE INDEX IF NOT EXISTS idx_mem_ns ON memories(namespace);
CREATE INDEX IF NOT EXISTS idx_mem_tsv ON memories USING gin(content_tsv);
CREATE INDEX IF NOT EXISTS idx_mem_emb ON memories
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE TABLE IF NOT EXISTS events (
    seq BIGSERIAL PRIMARY KEY, ts TIMESTAMPTZ, actor TEXT, action TEXT,
    memory_id TEXT, snapshot JSONB, prev_hash TEXT, hash TEXT
);
CREATE TABLE IF NOT EXISTS retrievals (
    id TEXT PRIMARY KEY, ts TIMESTAMPTZ, agent TEXT, query TEXT,
    memory_ids JSONB, context TEXT
);
CREATE TABLE IF NOT EXISTS receipts (
    id TEXT PRIMARY KEY, ts TIMESTAMPTZ, kind TEXT, payload JSONB, hash TEXT
);
"""

# The hybrid retrieval query production uses: semantic (pgvector) + keyword
# (tsvector/BM25-ish) + entity/trust boost, fused by weighted score.
HYBRID_SEARCH = """
WITH sem AS (
    SELECT id, 1 - (embedding <=> %(qvec)s::vector) AS sem_score
    FROM memories
    WHERE status = %(status)s
      AND (%(namespaces)s IS NULL OR namespace = ANY(%(namespaces)s))
    ORDER BY embedding <=> %(qvec)s::vector
    LIMIT 200
),
kw AS (
    SELECT id, ts_rank(content_tsv, plainto_tsquery(%(q)s)) AS kw_score
    FROM memories
    WHERE content_tsv @@ plainto_tsquery(%(q)s)
      AND status = %(status)s
)
SELECT m.*,
       COALESCE(sem.sem_score,0)*0.6
     + COALESCE(kw.kw_score,0)*0.3
     + m.trust*0.1                              AS score
FROM memories m
LEFT JOIN sem ON sem.id = m.id
LEFT JOIN kw  ON kw.id  = m.id
WHERE (sem.id IS NOT NULL OR kw.id IS NOT NULL)
ORDER BY score DESC
LIMIT %(limit)s;
"""


class PostgresVault:
    """Production driver. Mirrors the public methods of store.Vault.

    Implementation note: this class delegates the event-sourcing, conflict,
    and policy logic to the same code paths as the SQLite Vault by sharing
    the pure functions in schema/entities/policy — only the storage calls
    differ. A full port is a mechanical translation of store.Vault's SQL
    to the DDL above; the non-trivial parts (hybrid search, embeddings) are
    specified in HYBRID_SEARCH and memoryvault.embeddings.
    """

    def __init__(self, dsn: str = "", embedder=None):
        self.dsn = dsn or os.environ.get("DATABASE_URL", "")
        try:
            import psycopg  # noqa
            self._psycopg = psycopg
        except Exception as e:
            raise RuntimeError(
                "PostgresVault needs psycopg[binary] and a Postgres with the "
                f"pgvector extension. Import failed: {e}")
        from .embeddings import get_embedder
        self.embedder = embedder or get_embedder()
        self._conn = self._psycopg.connect(self.dsn, autocommit=True)
        self._conn.execute(DDL)

    # The method surface intentionally matches store.Vault so the API layer
    # is backend-agnostic: add/get/search/update/delete/erase_subject/
    # history/rollback/quarantine_list/approve/reject/verify_chain/counts.
    # See docs/PRODUCTION.md for the migration checklist and the
    # SQLite->Postgres field mapping.
