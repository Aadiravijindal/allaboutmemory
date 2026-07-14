"""Real Temporal workflows (optional) — the production-grade sync runtime.

Our `durable.py` queue covers the same contract (retries, backoff,
dead-letter) with zero infra, and stays the default. This module is the
drop-in upgrade for teams that run a Temporal cluster: identical semantics,
but Temporal owns durability, retries, and visibility.

Activates only if `temporalio` is installed and MV_TEMPORAL_HOST is set;
otherwise the API transparently uses the durable queue. Nothing here runs
at import time.
"""
from __future__ import annotations

import os
from datetime import timedelta

try:
    from temporalio import workflow, activity
    from temporalio.common import RetryPolicy
    HAVE_TEMPORAL = True
except Exception:  # pragma: no cover
    HAVE_TEMPORAL = False


if HAVE_TEMPORAL:  # pragma: no cover - needs a Temporal cluster

    @activity.defn
    async def pull_activity(org: str) -> dict:
        from .api import cp, build_registry
        from .sync import SyncEngine
        eng = SyncEngine(cp.vault_for(org), build_registry())
        return {"pulled": eng.pull_all()}

    @activity.defn
    async def project_activity(org: str) -> dict:
        from .api import cp, build_registry
        from .sync import SyncEngine
        eng = SyncEngine(cp.vault_for(org), build_registry())
        return {"projected": eng.project_all()}

    @workflow.defn
    class SyncWorkflow:
        """Durable, retried, resumable full sync for one org."""

        @workflow.run
        async def run(self, org: str) -> dict:
            retry = RetryPolicy(maximum_attempts=5,
                                initial_interval=timedelta(seconds=2),
                                backoff_coefficient=2.0)
            pulled = await workflow.execute_activity(
                pull_activity, org, start_to_close_timeout=timedelta(minutes=10),
                retry_policy=retry)
            projected = await workflow.execute_activity(
                project_activity, org,
                start_to_close_timeout=timedelta(minutes=10), retry_policy=retry)
            return {"pulled": pulled, "projected": projected}


async def run_worker():  # pragma: no cover - needs a Temporal cluster
    """Start a Temporal worker. `python -m memoryvault.temporal_workflows`."""
    if not HAVE_TEMPORAL:
        raise RuntimeError("pip install temporalio and set MV_TEMPORAL_HOST")
    from temporalio.client import Client
    from temporalio.worker import Worker
    client = await Client.connect(os.environ.get("MV_TEMPORAL_HOST",
                                                  "localhost:7233"))
    worker = Worker(client, task_queue="memoryvault-sync",
                    workflows=[SyncWorkflow],
                    activities=[pull_activity, project_activity])
    await worker.run()


def temporal_enabled() -> bool:
    return HAVE_TEMPORAL and bool(os.environ.get("MV_TEMPORAL_HOST"))


if __name__ == "__main__":  # pragma: no cover
    import asyncio
    asyncio.run(run_worker())
