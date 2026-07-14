"""The evidence locker — raw vendor exports, saved immutably.

Before a rescue normalizes anything, the ORIGINAL export is stored
untouched, with a content hash. This is the "we can prove what we received"
artifact auditors and the verification report reference.

Production: an S3 bucket in the CUSTOMER's account (object-lock / WORM for
immutability). Demo: local filesystem. Same interface either way; activates
S3 when MV_LOCKER_BUCKET is set (needs boto3).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Optional


class EvidenceLocker:
    def put(self, org: str, system: str, raw_bytes: bytes) -> dict:
        raise NotImplementedError

    def get(self, key: str) -> bytes:
        raise NotImplementedError

    @staticmethod
    def _meta(org, system, raw_bytes) -> dict:
        h = hashlib.sha256(raw_bytes).hexdigest()
        return {"org": org, "system": system, "sha256": h,
                "bytes": len(raw_bytes), "stored_at": time.time(),
                "key": f"{org}/{system}/{int(time.time())}_{h[:12]}.raw"}


class LocalLocker(EvidenceLocker):
    def __init__(self, root: str = "data/locker"):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def put(self, org: str, system: str, raw_bytes: bytes) -> dict:
        meta = self._meta(org, system, raw_bytes)
        path = os.path.join(self.root, meta["key"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(raw_bytes)
        with open(path + ".meta.json", "w") as f:
            json.dump(meta, f)
        meta["uri"] = f"file://{os.path.abspath(path)}"
        return meta

    def get(self, key: str) -> bytes:
        with open(os.path.join(self.root, key), "rb") as f:
            return f.read()


class S3Locker(EvidenceLocker):  # pragma: no cover - needs AWS
    """Customer-account S3 with object-lock for WORM immutability."""

    def __init__(self, bucket: str, prefix: str = "memoryvault/locker"):
        import boto3
        self.s3 = boto3.client("s3")
        self.bucket = bucket
        self.prefix = prefix

    def put(self, org: str, system: str, raw_bytes: bytes) -> dict:
        meta = self._meta(org, system, raw_bytes)
        key = f"{self.prefix}/{meta['key']}"
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=raw_bytes,
                           Metadata={"sha256": meta["sha256"], "org": org})
        meta["uri"] = f"s3://{self.bucket}/{key}"
        return meta

    def get(self, key: str) -> bytes:
        obj = self.s3.get_object(Bucket=self.bucket, Key=key)
        return obj["Body"].read()


def get_locker() -> EvidenceLocker:
    bucket = os.environ.get("MV_LOCKER_BUCKET", "")
    if bucket:
        try:
            return S3Locker(bucket)
        except Exception:
            pass
    return LocalLocker(os.path.join(os.environ.get("MV_DATA", "data"),
                                    "locker"))
