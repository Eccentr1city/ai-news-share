"""GDELT timelines: DOC 2.0 (online articles) and TV 2.0 (cable news airtime).

Both return `timelinevol`: the *percentage of all monitored content* matching
the query, daily. DOC covers 2017-01-01+; TV (Internet Archive TV News)
covers 2009-07+. GDELT rate-limits hard (1 request / 5 s, and cools down
offenders for a while), so calls are paced and failures are non-fatal.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

from . import http
from .topics import TOPICS

log = logging.getLogger(__name__)

DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
TV_URL = "https://api.gdeltproject.org/api/v2/tv/tv"
DOC_SCOPE = "sourcecountry:US sourcelang:english"
TV_SCOPE = "(station:CNN OR station:FOXNEWS OR station:MSNBC)"
DOC_START = date(2017, 1, 1)
TV_START = date(2017, 1, 1)  # TV goes back to 2009 but 2017 keeps the two comparable
INTERVAL = 6.0


class GdeltError(RuntimeError):
    pass


def _timeline(url: str, query: str, start: date, end: date) -> dict[str, float]:
    params = {
        "query": query,
        "mode": "timelinevol",
        "format": "json",
        "startdatetime": start.strftime("%Y%m%d000000"),
        "enddatetime": end.strftime("%Y%m%d235959"),
    }
    r = http.get(url, params, min_interval=INTERVAL)
    try:
        js = r.json()
    except json.JSONDecodeError:
        raise GdeltError(r.text[:200].strip())
    out: dict[str, list[float]] = {}
    for series in js.get("timeline", []):
        for pt in series.get("data", []):
            d = pt["date"][:8]
            out.setdefault(f"{d[:4]}-{d[4:6]}-{d[6:]}", []).append(float(pt["value"]))
    # TV returns one series per station; average them so the unit stays "% of airtime".
    return {d: sum(v) / len(v) for d, v in out.items()}


def _year_chunks(start: date, end: date):
    s = start
    while s <= end:
        e = min(date(s.year, 12, 31), end)
        yield s, e
        s = e + timedelta(days=1)


def backfill(kind: str, start: date, end: date, data_dir: Path) -> bool:
    """kind in {"doc","tv"}. Returns False (without raising) if GDELT refuses."""
    url, scope = (DOC_URL, DOC_SCOPE) if kind == "doc" else (TV_URL, TV_SCOPE)
    path = data_dir / f"gdelt_{kind}.json"
    prev = json.loads(path.read_text()) if path.exists() else {"series": {}}
    series: dict[str, dict[str, float]] = {k: dict(v) for k, v in prev["series"].items()}
    # Only refetch the current year unless a topic has no history yet.
    for key, topic in TOPICS.items():
        have = series.setdefault(key, {})
        first = start if not have else date(end.year, 1, 1)
        for s, e in _year_chunks(first, end):
            try:
                pts = _timeline(url, f"{topic.gdelt_query} {scope}", s, e)
            except (GdeltError, Exception) as ex:  # noqa: BLE001
                log.warning("gdelt %s %s %s..%s failed: %s", kind, key, s, e, str(ex)[:120])
                if not have:
                    return False
                continue
            have.update(pts)
            log.info("gdelt %s %s %s..%s: %d days", kind, key, s, e, len(pts))
    path.write_text(
        json.dumps(
            {
                "meta": {
                    "source": "GDELT DOC 2.0 timelinevol (US, English)" if kind == "doc" else "GDELT TV 2.0 timelinevol (CNN/Fox/MSNBC avg)",
                    "unit": "% of monitored articles" if kind == "doc" else "% of 15-second airtime clips",
                    "queries": {k: t.gdelt_query for k, t in TOPICS.items()},
                    "scope": scope,
                },
                "series": {k: dict(sorted(v.items())) for k, v in series.items()},
            }
        )
    )
    return True
