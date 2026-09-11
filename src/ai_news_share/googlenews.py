"""Google News "Top stories" RSS: the closest free thing to "the 100 top US stories right now".

No history (only from the day you start collecting), so this is the
going-forward front-page number, appended once per run.
"""
from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from . import http
from .topics import TOPICS

log = logging.getLogger(__name__)

FEEDS = {
    "google_top": "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
    "google_us": "https://news.google.com/rss/headlines/section/topic/NATION?hl=en-US&gl=US&ceid=US:en",
}


BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"


def fetch(url: str) -> list[dict]:
    # Google returns 503 to some datacenter IPs (e.g. GitHub runners) for the default UA; retry as a browser.
    try:
        r = http.get(url, tries=2)
    except Exception:  # noqa: BLE001
        r = http.client().get(url, headers={"User-Agent": BROWSER_UA, "Accept": "application/rss+xml,text/xml;q=0.9,*/*;q=0.8"})
        r.raise_for_status()
    root = ET.fromstring(r.content)
    items = []
    for it in root.iter("item"):
        raw = (it.findtext("title") or "").strip()
        title = re.sub(r"\s+-\s+[^-]+$", "", raw)  # strip trailing " - Source"
        items.append({"title": title, "source": raw[len(title) :].lstrip(" -"), "link": it.findtext("link", "")})
    return items


def snapshot(data_dir: Path, limit: int = 100) -> dict:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    summary_path, raw_path = data_dir / "topstories.jsonl", data_dir / "topstories_raw.jsonl"
    result = {}
    with summary_path.open("a") as fs, raw_path.open("a") as fr:
        for feed, url in FEEDS.items():
            try:
                items = fetch(url)[:limit]
            except Exception as ex:  # noqa: BLE001
                log.warning("feed %s failed: %s", feed, ex)
                continue
            row = {"ts": ts, "feed": feed, "n": len(items)}
            for it in items:
                it["topics"] = {k: t.matches(it["title"]) for k, t in TOPICS.items()}
                fr.write(json.dumps({"ts": ts, "feed": feed, **it}, ensure_ascii=False) + "\n")
            for k in TOPICS:
                row[k] = sum(1 for it in items if it["topics"][k])
            fs.write(json.dumps(row) + "\n")
            result[feed] = row
            log.info("snapshot %s: %d/%d AI headlines", feed, row["ai"], row["n"])
    return result


# ---------------------------------------------------------------- wayback ---
# The Internet Archive captured the Google News RSS feed sporadically: every few
# days in 2017-18 (old URL), ~monthly in 2019-2020, ~weekly by 2024-25. Each
# capture is one snapshot of the top stories at that moment, so this gives a
# coarse retroactive series. Rows are stored with feed="google_top_wayback".
import time as _time
from datetime import timedelta as _td
from pathlib import Path as _Path
from urllib.parse import quote as _quote

WAYBACK_URLS = [
    "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/news/rss/?hl=en&ned=us&gl=US",
    "https://news.google.com/news/rss/?ned=us&hl=en",
]
CDX = "http://web.archive.org/cdx/search/cdx"
WB_INTERVAL = 2.5


def wayback_captures(start_year: int = 2017) -> list[tuple[str, str]]:
    """(timestamp, original_url) for one successful capture per day across the URL variants."""
    out: dict[str, tuple[str, str]] = {}
    for u in WAYBACK_URLS:
        params = {"url": u, "output": "json", "fl": "timestamp,original,statuscode", "filter": "statuscode:200",
                  "collapse": "timestamp:8", "from": str(start_year), "to": "2099"}
        try:
            rows = http.get(CDX, params, min_interval=WB_INTERVAL, tries=3).json()[1:]
        except Exception as ex:  # noqa: BLE001
            log.warning("cdx %s failed: %s", u, type(ex).__name__)
            continue
        for ts, orig, _ in rows:
            out.setdefault(ts[:8], (ts, orig))  # first variant wins per day
    return sorted(out.values())


def backfill_wayback(data_dir: _Path, *, budget_s: float = 30 * 60, limit: int = 100) -> int:
    """Fetch un-fetched Wayback captures (oldest first, up to `limit`), append rows like snapshot()."""
    summary_path, raw_path = data_dir / "topstories.jsonl", data_dir / "topstories_raw.jsonl"
    have = set()
    if summary_path.exists():
        for line in summary_path.read_text().splitlines():
            r = json.loads(line)
            if r.get("feed") == "google_top_wayback":
                have.add(r["ts"][:10])
    caps = [c for c in wayback_captures() if f"{c[0][:4]}-{c[0][4:6]}-{c[0][6:8]}" not in have]
    log.info("wayback: %d captures available, %d not yet fetched", len(caps) + len(have), len(caps))
    t0, n = _time.monotonic(), 0
    with summary_path.open("a") as fs, raw_path.open("a") as fr:
        for ts, orig in caps[:limit]:
            if _time.monotonic() - t0 > budget_s:
                break
            url = f"http://web.archive.org/web/{ts}id_/{orig}"
            try:
                items = fetch_from_bytes(http.get(url, min_interval=WB_INTERVAL, tries=3).content)[:limit]
            except Exception as ex:  # noqa: BLE001
                log.warning("wayback %s failed: %s", ts, type(ex).__name__)
                continue
            if not items:
                continue
            iso = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}T{ts[8:10]}:{ts[10:12]}:{ts[12:14]}+00:00"
            row = {"ts": iso, "feed": "google_top_wayback", "n": len(items), "source_url": orig}
            for it in items:
                it["topics"] = {k: t.matches(it["title"]) for k, t in TOPICS.items()}
                fr.write(json.dumps({"ts": iso, "feed": "google_top_wayback", **it}, ensure_ascii=False) + "\n")
            for k in TOPICS:
                row[k] = sum(1 for it in items if it["topics"][k])
            fs.write(json.dumps(row) + "\n")
            fs.flush(); fr.flush()  # progress is visible and survives interruption
            n += 1
            log.info("wayback %s: %d headlines, %d AI, %d covid", iso[:10], row["n"], row["ai"], row["covid"])
    return n


def fetch_from_bytes(content: bytes) -> list[dict]:
    root = ET.fromstring(content)
    items = []
    for it in root.iter("item"):
        raw = (it.findtext("title") or "").strip()
        title = re.sub(r"\s+-\s+[^-]+$", "", raw)
        items.append({"title": title, "source": raw[len(title):].lstrip(" -"), "link": it.findtext("link", "")})
    return items
