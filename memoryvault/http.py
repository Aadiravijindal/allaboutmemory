"""Hardened HTTP client for connectors: retries, exponential backoff,
rate-limit (429/Retry-After) handling, timeouts. The unglamorous plumbing
every real integration needs.
"""
from __future__ import annotations

import time
import logging

log = logging.getLogger("memoryvault.http")

try:
    import requests
    HAVE_REQUESTS = True
except Exception:  # pragma: no cover
    HAVE_REQUESTS = False


class HttpError(Exception):
    pass


def request(method: str, url: str, *, headers=None, params=None, json=None,
            timeout: int = 30, max_retries: int = 5, backoff: float = 1.5):
    if not HAVE_REQUESTS:
        raise HttpError("install 'requests' to use live connectors")
    attempt = 0
    while True:
        attempt += 1
        try:
            r = requests.request(method, url, headers=headers, params=params,
                                  json=json, timeout=timeout)
        except requests.RequestException as e:
            if attempt >= max_retries:
                raise HttpError(f"{method} {url} failed: {e}")
            _sleep(backoff, attempt)
            continue
        # rate limited -> respect Retry-After
        if r.status_code == 429 and attempt < max_retries:
            wait = float(r.headers.get("Retry-After", backoff ** attempt))
            log.warning("429 from %s, waiting %.1fs", url, wait)
            time.sleep(min(wait, 60))
            continue
        # transient server errors -> backoff
        if r.status_code >= 500 and attempt < max_retries:
            _sleep(backoff, attempt)
            continue
        if not r.ok:
            raise HttpError(f"{method} {url} -> {r.status_code}: {r.text[:200]}")
        return r


def _sleep(backoff: float, attempt: int):
    time.sleep(min(backoff ** attempt, 30))


def get_json(url, **kw):
    return request("GET", url, **kw).json()


def post_json(url, **kw):
    return request("POST", url, **kw).json()
