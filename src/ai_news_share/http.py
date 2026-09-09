"""Shared HTTP helper: one client, polite User-Agent, retries, per-host pacing."""
from __future__ import annotations

import logging
import time

import httpx

log = logging.getLogger(__name__)

UA = "ai-news-share/0.1 (+https://github.com/Eccentr1city/ai-news-share; research tool)"

_client: httpx.Client | None = None
_last_call: dict[str, float] = {}


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(headers={"User-Agent": UA}, timeout=90, follow_redirects=True)
    return _client


def get(url: str, params: dict | None = None, *, min_interval: float = 0.0, tries: int = 4) -> httpx.Response:
    """GET with retry/backoff. `min_interval` enforces a gap between calls to the same host."""
    host = httpx.URL(url).host
    for attempt in range(tries):
        wait = min_interval - (time.monotonic() - _last_call.get(host, 0.0))
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.monotonic()
        try:
            r = client().get(url, params=params)
            if r.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError(f"{r.status_code}", request=r.request, response=r)
            r.raise_for_status()
            return r
        except (httpx.HTTPError, httpx.TransportError) as e:
            if attempt == tries - 1:
                raise
            backoff = 5 * (attempt + 1)
            log.warning("%s -> %s; retrying in %ss", url, e, backoff)
            time.sleep(backoff)
    raise RuntimeError("unreachable")
