"""GDELT timelines: DOC 2.0 (online articles) and TV 2.0 (cable news airtime).

Both return `timelinevol`: the *percentage of all monitored content* matching
the query, daily. DOC covers 2017-01-01+; the TV archive API currently ends in
October 2024.

GDELT has no paid tier and throttles aggressively (nominally 1 request / 5 s,
in practice long cool-downs after any burst). So this module is a *slow
crawler with a persistent cache*: the work is split into (kind, topic, year)
chunks, each finished chunk is recorded in docs/data/gdelt_<kind>.json, and
every run just does as many unfinished chunks as its time budget allows,
pausing INTERVAL seconds between requests and backing off for minutes on a
429. Re-run it (or let the daily job run it) until nothing is left.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

from . import http
from .topics import TOPICS

log = logging.getLogger(__name__)

DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
TV_URL = "https://api.gdeltproject.org/api/v2/tv/tv"
DOC_SCOPE = "sourcecountry:US sourcelang:english"
TV_SCOPE = "(station:CNN OR station:FOXNEWS OR station:MSNBC)"
START = date(2017, 1, 1)
INTERVAL = 20.0  # seconds between requests: slow on purpose
BACKOFF = (60, 120, 240, 480)  # seconds to wait after successive throttle responses
REFRESH_CURRENT_YEAR_AFTER_DAYS = 1


class Throttled(RuntimeError):
    pass


def _timeline(url: str, query: str, start: date, end: date) -> dict[str, float]:
    params = {
        "query": query,
        "mode": "timelinevol",
        "format": "json",
        "startdatetime": start.strftime("%Y%m%d000000"),
        "enddatetime": end.strftime("%Y%m%d235959"),
    }
    try:
        r = http.get(url, params, min_interval=INTERVAL, tries=1)
    except httpx.HTTPStatusError as ex:
        if ex.response is not None and ex.response.status_code == 429:
            raise Throttled("HTTP 429") from ex
        raise
    text = r.text.strip()
    if not text.startswith("{"):
        if "limit requests" in text or r.status_code == 429:
            raise Throttled(text[:120])
        raise RuntimeError(text[:160])  # e.g. "Your query was too short or too long."
    js = json.loads(text)
    out: dict[str, list[float]] = {}
    for series in js.get("timeline", []):
        for pt in series.get("data", []):
            d = pt["date"][:8]
            out.setdefault(f"{d[:4]}-{d[4:6]}-{d[6:]}", []).append(float(pt["value"]))
    # TV returns one series per station; average them so the unit stays "% of airtime".
    return {d: sum(v) / len(v) for d, v in out.items()}


def _chunks(start: date, end: date):
    s = start
    while s <= end:
        e = min(date(s.year, 12, 31), end)
        yield s, e
        s = e + timedelta(days=1)


def _load(path: Path, kind: str, scope: str) -> dict:
    if path.exists():
        st = json.loads(path.read_text())
    else:
        st = {"meta": {}, "series": {}, "done": {}}
    st["meta"].update(
        {
            "source": "GDELT DOC 2.0 timelinevol (US, English)" if kind == "doc" else "GDELT TV 2.0 timelinevol (CNN/Fox/MSNBC avg)",
            "unit": "% of monitored articles" if kind == "doc" else "% of 15-second airtime clips",
            "queries": {k: t.gdelt_query for k, t in TOPICS.items()},
            "scope": scope,
        }
    )
    st.setdefault("done", {})
    st.setdefault("series", {})
    return st


def _merge_from_disk(st: dict, path: Path) -> None:
    """Union the on-disk file's finished chunks into `st` (without overriding chunks st fetched itself)."""
    if not path.exists():
        return
    try:
        other = json.loads(path.read_text())
    except json.JSONDecodeError:
        return
    for tag, when in other.get("done", {}).items():
        if tag.endswith(":query"):
            continue
        key, year = tag.split(":")
        if tag not in st["done"] and other["done"].get(f"{key}:query") == st["done"].get(f"{key}:query", other["done"].get(f"{key}:query")):
            st["done"][tag] = when
            st["done"].setdefault(f"{key}:query", other["done"].get(f"{key}:query"))
            series = st["series"].setdefault(key, {})
            for d, v in other.get("series", {}).get(key, {}).items():
                if d.startswith(year):
                    series[d] = v
            st["series"][key] = dict(sorted(series.items()))


def merge_files(a: Path, b: Path, out: Path) -> dict:
    """Union two gdelt_*.json files (used after a git pull that brought CI's chunks)."""
    st = json.loads(a.read_text())
    _merge_from_disk(st, b)
    out.write_text(json.dumps(st))
    return st


def pending(kind: str, end: date, data_dir: Path) -> list[tuple[str, date, date]]:
    """Chunks not yet fetched (or the current year, if it is stale)."""
    scope = DOC_SCOPE if kind == "doc" else TV_SCOPE
    st = _load(data_dir / f"gdelt_{kind}.json", kind, scope)
    todo = []
    today = date.today().isoformat()
    for key, topic in TOPICS.items():
        # If the query text changed, everything for that topic is stale.
        if st["done"].get(f"{key}:query") not in (None, topic.gdelt_query):
            for k in [k for k in st["done"] if k.startswith(f"{key}:")]:
                del st["done"][k]
            st["series"][key] = {}
        for s, e in _chunks(START, end):
            tag = f"{key}:{s.year}"
            fetched = st["done"].get(tag)
            current = s.year == end.year
            stale = current and fetched and (date.fromisoformat(today) - date.fromisoformat(fetched[:10])).days >= REFRESH_CURRENT_YEAR_AFTER_DAYS
            if not fetched or stale:
                todo.append((key, s, e))
    return todo


def crawl(kind: str, end: date, data_dir: Path, *, budget_s: float = 25 * 60) -> dict:
    """Fetch pending chunks for `kind` until the time budget runs out.

    Returns {"fetched": n, "pending": m, "throttled": bool}. Never raises for
    GDELT-side trouble; progress is saved after every chunk.
    """
    url, scope = (DOC_URL, DOC_SCOPE) if kind == "doc" else (TV_URL, TV_SCOPE)
    path = data_dir / f"gdelt_{kind}.json"
    st = _load(path, kind, scope)
    todo = pending(kind, end, data_dir)
    t0 = time.monotonic()
    fetched, throttles = 0, 0
    for key, s, e in todo:
        if time.monotonic() - t0 > budget_s:
            break
        topic = TOPICS[key]
        try:
            pts = _timeline(url, f"{topic.gdelt_query} {scope}", s, e)
        except Throttled as ex:
            throttles += 1
            wait = BACKOFF[min(throttles, len(BACKOFF)) - 1]  # stay at the longest backoff while budget remains
            log.warning("gdelt %s throttled (%s); sleeping %ds", kind, str(ex)[:60], wait)
            if time.monotonic() - t0 + wait > budget_s:
                break
            time.sleep(wait)
            todo.append((key, s, e))  # retry this chunk after the others
            continue
        except (httpx.HTTPError, RuntimeError, json.JSONDecodeError) as ex:
            log.warning("gdelt %s %s %s: %s", kind, key, s.year, str(ex)[:120])
            if "too short or too long" in str(ex):
                break  # query needs fixing in topics.py; retrying is pointless
            time.sleep(INTERVAL)
            continue
        throttles = 0
        series = st["series"].setdefault(key, {})
        for d in [d for d in series if s.isoformat() <= d <= e.isoformat()]:
            del series[d]
        series.update(pts)
        st["done"][f"{key}:{s.year}"] = date.today().isoformat()
        st["done"][f"{key}:query"] = topic.gdelt_query
        fetched += 1
        st["series"][key] = dict(sorted(series.items()))
        _merge_from_disk(st, path)  # another crawler (CI, a git pull) may have added chunks meanwhile
        path.write_text(json.dumps(st))
        log.info("gdelt %s %s %d: %d days", kind, key, s.year, len(pts))
    left = len(pending(kind, end, data_dir))
    log.info("gdelt %s: fetched %d chunks this run, %d pending", kind, fetched, left)
    return {"fetched": fetched, "pending": left, "throttled": throttles > 0}
