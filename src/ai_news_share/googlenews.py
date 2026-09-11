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
