"""Durable sync — syncs that never silently fail (#7).

A persistent job queue backed by the vault DB: every sync job is recorded,
retried with exponential backoff on failure, and sent to a dead-letter
table after max attempts (so nothing fails silently — a human sees it).
Resumable across restarts because state lives in the DB, not memory.

This is the Temporal-workflow contract without requiring a Temporal server
for the demo. To swap in real Temporal, implement `enqueue`/`run_due`
against a Temporal client — the interface is identical. A background
scheduler (`start_scheduler`) drives the "runs all day" loop.
"""
from __future__ import annotations

import json
import threading
import time
import traceback
from datetime import datetime, timezone, timedelta

from .store import Vault
from .sync import SyncEngine
from .connectors import ConnectorRegistry


class DurableSync:
    def __init__(self, vault: Vault, registry: ConnectorRegistry,
                 max_attempts: int = 5, base_backoff: float = 2.0):
        self.vault = vault
        self.engine = SyncEngine(vault, registry)
        self.max_attempts = max_attempts
        self.base_backoff = base_backoff
        self._init_tables()

    def _init_tables(self):
        self.vault.db.executescript("""
        CREATE TABLE IF NOT EXISTS sync_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, target TEXT,
            state TEXT DEFAULT 'pending', attempts INTEGER DEFAULT 0,
            run_after TEXT, created_at TEXT, updated_at TEXT, last_error TEXT
        );
        CREATE TABLE IF NOT EXISTS sync_deadletter (
            id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER, kind TEXT,
            target TEXT, error TEXT, failed_at TEXT
        );
        """)
        self.vault.db.commit()

    def _now(self):
        return datetime.now(timezone.utc)

    def enqueue(self, kind: str, target: str = "*"):
        now = self._now().isoformat()
        self.vault.db.execute(
            "INSERT INTO sync_jobs(kind,target,run_after,created_at,updated_at)"
            " VALUES (?,?,?,?,?)", (kind, target, now, now, now))
        self.vault.db.commit()

    def _due(self):
        now = self._now().isoformat()
        return self.vault.db.execute(
            "SELECT * FROM sync_jobs WHERE state IN ('pending','retry')"
            " AND run_after<=? ORDER BY id LIMIT 20", (now,)).fetchall()

    def run_due(self) -> dict:
        """Process all due jobs once. Returns a summary."""
        done, failed, dead = 0, 0, 0
        for job in self._due():
            try:
                self._execute(job)
                self.vault.db.execute(
                    "UPDATE sync_jobs SET state='done',updated_at=? WHERE id=?",
                    (self._now().isoformat(), job["id"]))
                done += 1
            except Exception as e:
                attempts = job["attempts"] + 1
                err = f"{e}\n{traceback.format_exc()[-400:]}"
                if attempts >= self.max_attempts:
                    self.vault.db.execute(
                        "INSERT INTO sync_deadletter(job_id,kind,target,error,"
                        "failed_at) VALUES (?,?,?,?,?)",
                        (job["id"], job["kind"], job["target"], err,
                         self._now().isoformat()))
                    self.vault.db.execute(
                        "UPDATE sync_jobs SET state='dead',attempts=?,"
                        "last_error=?,updated_at=? WHERE id=?",
                        (attempts, err, self._now().isoformat(), job["id"]))
                    dead += 1
                else:
                    delay = self.base_backoff ** attempts
                    run_after = (self._now() + timedelta(seconds=delay)).isoformat()
                    self.vault.db.execute(
                        "UPDATE sync_jobs SET state='retry',attempts=?,"
                        "run_after=?,last_error=?,updated_at=? WHERE id=?",
                        (attempts, run_after, err, self._now().isoformat(),
                         job["id"]))
                    failed += 1
            self.vault.db.commit()
        return {"done": done, "retried": failed, "deadlettered": dead}

    def _execute(self, job):
        if job["kind"] == "pull":
            self.engine.pull_all()
        elif job["kind"] == "project":
            self.engine.project_all()
        elif job["kind"] == "full":
            self.engine.sync_once()
        else:
            raise ValueError(f"unknown job kind {job['kind']}")

    def deadletters(self) -> list:
        return [dict(r) for r in self.vault.db.execute(
            "SELECT * FROM sync_deadletter ORDER BY failed_at DESC")]

    def stats(self) -> dict:
        rows = self.vault.db.execute(
            "SELECT state,COUNT(*) n FROM sync_jobs GROUP BY state")
        return {r["state"]: r["n"] for r in rows}

    # ---- background scheduler: the "runs all day" loop -------------------
    def start_scheduler(self, interval_seconds: int = 3600) -> threading.Thread:
        def loop():
            while True:
                self.enqueue("full")
                self.run_due()
                time.sleep(interval_seconds)
        t = threading.Thread(target=loop, daemon=True)
        t.start()
        return t
