"""New York Times Archive API: every article per month since 1851, with print
page numbers, so "page 1 of the print paper" is a literal front-page series.

Needs a free key from https://developer.nytimes.com (set NYT_API_KEY in the
environment or in a .env file next to pyproject.toml). Limits: 500 requests
per day, 5 per minute; one request returns a whole month, so a 2017->today
backfill is ~120 requests (~25 minutes at the rate limit) and each later run
refreshes only the current month.

Output: docs/data/nyt_daily.json with, per day, the number of A1 (front page)
articles and how many match each topic (headline + abstract), plus
nyt_items.jsonl with every page-one article of every section for auditing.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import date
from pathlib import Path

from . import http, labels
from .config import env
from .topics import TOPICS

log = logging.getLogger(__name__)

URL = "https://api.nytimes.com/svc/archive/v1/{year}/{month}.json"
INTERVAL = 13.0  # 5 requests / minute
START = date(2017, 1, 1)


def api_key() -> str | None:
    return env("NYT_API_KEY")


FRONT_SECTION = "A"  # A1 = the front page; B1/C1/D1 are section fronts


def is_page_one(doc: dict) -> bool:
    """Page 1 of any print section (kept in the item log so the choice can be revisited)."""
    return str(doc.get("print_page", "")).strip() == "1" and str(doc.get("document_type", "")).lower() == "article"


def is_front_page(item: dict) -> bool:
    return item.get("print_section", "") == FRONT_SECTION


def item_from_doc(doc: dict) -> dict:
    headline = (doc.get("headline") or {}).get("main") or ""
    abstract = doc.get("abstract") or doc.get("snippet") or ""
    text = f"{headline} {abstract}"  # text only, like the other sources (NYT subject tags are applied liberally)
    return {
        "date": (doc.get("pub_date") or "")[:10],
        "headline": headline,
        "abstract": abstract,
        "section": doc.get("section_name") or doc.get("news_desk") or "",
        "print_section": doc.get("print_section") or "",
        "url": doc.get("web_url", ""),
        "topics": {k: t.matches(text) for k, t in TOPICS.items()},
    }


def fetch_month(year: int, month: int, key: str) -> list[dict]:
    r = http.get(URL.format(year=year, month=month), {"api-key": key}, min_interval=INTERVAL, tries=3)
    return r.json().get("response", {}).get("docs", [])


def months(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def backfill(data_dir: Path, start: date = START, end: date | None = None, *, budget_s: float = 40 * 60, refetch_from: str | None = None) -> bool:
    """Fetch months not yet cached (always refresh the current month). Returns False if no key.

    `refetch_from="2025-01"` discards cached months from that month on.
    """
    key = api_key()
    if not key:
        log.info("NYT_API_KEY not set; skipping NYT")
        return False
    end = end or date.today()
    data_dir.mkdir(parents=True, exist_ok=True)
    items_path, daily_path = data_dir / "nyt_items.jsonl", data_dir / "nyt_daily.json"
    by_month: dict[str, list[dict]] = {}
    if items_path.exists():
        for line in items_path.read_text().splitlines():
            it = json.loads(line)
            by_month.setdefault(it["date"][:7], []).append(it)
    meta = json.loads(daily_path.read_text())["meta"] if daily_path.exists() else {}
    done = set(meta.get("months_done", []))
    if refetch_from:
        done = {m for m in done if m < refetch_from}
        by_month = {m: v for m, v in by_month.items() if m < refetch_from}
    current = end.strftime("%Y-%m")
    t0 = time.monotonic()
    for y, m in months(start, end):
        tag = f"{y}-{m:02d}"
        if tag in done and tag != current:
            continue
        if time.monotonic() - t0 > budget_s:
            log.warning("nyt: budget exhausted; re-run to continue")
            break
        try:
            docs = fetch_month(y, m, key)
        except Exception as ex:  # noqa: BLE001
            log.warning("nyt %s failed: %s", tag, str(ex)[:120])
            continue
        by_month[tag] = [item_from_doc(d) for d in docs if is_page_one(d)]
        done.add(tag)
        log.info("nyt %s: %d articles, %d on page 1", tag, len(docs), len(by_month[tag]))
        _write(by_month, done, items_path, daily_path)  # persist after every month
    _write(by_month, done, items_path, daily_path)
    return True


def _write(by_month: dict[str, list[dict]], done: set[str], items_path: Path, daily_path: Path) -> None:
    """Re-classify with the current patterns and write both files."""
    daily: dict[str, dict] = {}
    with items_path.open("w") as f:
        for tag in sorted(by_month):
            for it in by_month[tag]:
                text = f"{it['headline']} {it['abstract']}"
                it["topics"] = {k: t.matches(text) for k, t in TOPICS.items()}
                it["topics_llm"] = labels.llm_topics(items_path.parent, text.strip()) if is_front_page(it) else None
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
                if not is_front_page(it):
                    continue
                row = daily.setdefault(it["date"], {"n": 0, **{k: 0 for k in TOPICS}})
                row["n"] += 1
                for k in TOPICS:
                    row[k] += int(it["topics"][k])
                labels.add_llm_counts(row, it["topics_llm"])
    daily_path.write_text(
        json.dumps(
            {
                "meta": {
                    "source": "New York Times Archive API, page A1 articles",
                    "unit": "count of A1 (front page) articles per day; topic columns match headline+abstract",
                    "months_done": sorted(done),
                },
                "daily": dict(sorted(daily.items())),
            }
        )
    )
    log.debug("wrote %s (%d days)", daily_path, len(daily))
