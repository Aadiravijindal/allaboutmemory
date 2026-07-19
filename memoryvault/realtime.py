"""Real-time write-back — event-driven memory push (beyond daily sync).

Enterprises need memory to flow into their systems the moment it changes,
not on a batch timer. This registers webhook subscribers (an ERP endpoint,
a Slack app, another agent) and fires them on every memory event, with
retries. It's the push side of the "one brain, live" promise.
"""
from __future__ import annotations

import json
import os
import time


class RealtimeBus:
    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, "subscribers.json")
        self.log = os.path.join(data_dir, "realtime_deliveries.jsonl")
        os.makedirs(data_dir, exist_ok=True)
        self._subs = self._load()

    def _load(self) -> list:
        if os.path.exists(self.path):
            with open(self.path) as f:
                return json.load(f)
        return []

    def _save(self):
        with open(self.path, "w") as f:
            json.dump(self._subs, f, indent=2)

    def subscribe(self, url: str, events: list = None, secret: str = "") -> dict:
        sub = {"id": len(self._subs) + 1, "url": url,
               "events": events or ["add", "delete", "update"],
               "secret": secret, "created_at": time.time()}
        self._subs.append(sub)
        self._save()
        return {k: v for k, v in sub.items() if k != "secret"}

    def unsubscribe(self, sub_id: int) -> bool:
        before = len(self._subs)
        self._subs = [s for s in self._subs if s["id"] != sub_id]
        self._save()
        return len(self._subs) < before

    def list(self) -> list:
        return [{k: v for k, v in s.items() if k != "secret"} for s in self._subs]

    def publish(self, action: str, memory: dict) -> dict:
        """Fire matching subscribers. Uses the hardened HTTP client with
        retries; failures are logged, never silent."""
        delivered, failed = 0, 0
        payload = {"event": action, "memory": {
            "id": memory.get("id"), "subject": memory.get("subject"),
            "attribute": memory.get("attribute"), "value": memory.get("value"),
            "content": memory.get("content"), "ts": time.time()}}
        for s in self._subs:
            if action not in s["events"]:
                continue
            ok = self._deliver(s, payload)
            delivered += 1 if ok else 0
            failed += 0 if ok else 1
        return {"subscribers": len(self._subs), "delivered": delivered,
                "failed": failed}

    def _deliver(self, sub: dict, payload: dict) -> bool:
        try:
            from .http import request
            headers = {"content-type": "application/json"}
            if sub.get("secret"):
                headers["x-mv-signature"] = sub["secret"]
            request("POST", sub["url"], headers=headers, json=payload,
                    max_retries=3)
            self._record(sub["id"], payload["event"], "ok")
            return True
        except Exception as e:
            self._record(sub["id"], payload["event"], f"failed: {e}")
            return False

    def _record(self, sub_id, event, status):
        with open(self.log, "a") as f:
            f.write(json.dumps({"ts": time.time(), "sub": sub_id,
                                "event": event, "status": status}) + "\n")
