"""Wikipedia "Portal:Current events" as a curated daily list of top news items.

Why this source: it is the only free, keyless, editorially curated list of
"the important news of the day" with consistent daily coverage from ~2003 to
today, so Covid-2020 and AI-today are measured with the same instrument.
Each day has roughly 10-40 leaf items, so a rolling week is ~100-200 items:
a reasonable stand-in for "the top 100 stories".

Caveats (also in README): the portal is global, not US-only; it favors
discrete events over ongoing debates; volunteer editing standards drift.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Iterator

from . import http, labels
from .topics import TOPICS

log = logging.getLogger(__name__)

API = "https://en.wikipedia.org/w/api.php"
BATCH = 50  # MediaWiki max titles per query for anonymous users


def page_title(d: date) -> str:
    return f"Portal:Current events/{d.year} {d.strftime('%B')} {d.day}"


def title_to_date(title: str) -> date | None:
    m = re.match(r"Portal:Current events/(\d{4}) (\w+) (\d{1,2})$", title)
    if not m:
        return None
    from datetime import datetime

    return datetime.strptime(f"{m[1]} {m[2]} {m[3]}", "%Y %B %d").date()


@dataclass
class Item:
    date: str
    section: str
    context: str  # parent bullet(s), e.g. "COVID-19 pandemic > Aftermath of Black Monday"
    text: str
    sources: list[str]
    topics: dict[str, bool]


_WIKILINK = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]")
_EXTLINK = re.compile(r"\[(https?://\S+)(?:\s+\(([^)]*)\))?\]")
_MARKUP = re.compile(r"'{2,}|<[^>]+>|\{\{[^}]*\}\}")
_BOLD_HEADER = re.compile(r"'''[^']+'''\s*")


def clean(wikitext: str) -> tuple[str, list[str]]:
    """Strip wiki markup; return (plain text, [source names or urls])."""
    sources = [(name or url).replace("''", "").strip() for url, name in _EXTLINK.findall(wikitext)]
    t = _EXTLINK.sub("", wikitext)
    t = _WIKILINK.sub(r"\1", t)
    t = _MARKUP.sub("", t)
    return re.sub(r"\s+", " ", t).strip(), sources


def parse_day(d: date, wikitext: str) -> list[Item]:
    """Return the leaf bullet items of one day's page.

    Format (2017-today): ``;Section`` headers, then ``*``-nested bullets. A
    bullet with children is a topic heading (``*[[COVID-19 pandemic]]``);
    a bullet without children is a news item. Items are classified on their
    own text *plus* their ancestor bullets, since the topic often lives there.
    """
    lines = [l.rstrip() for l in wikitext.splitlines()]
    bullets: list[tuple[int, str]] = []  # (depth, raw)
    section_of: list[str] = []
    cur_section = ""
    for l in lines:
        if l.startswith(";"):  # 2017-2022 style section header
            cur_section = clean(l[1:])[0]
        elif _BOLD_HEADER.fullmatch(l):  # 2023+ style
            cur_section = clean(l)[0]
        elif l.startswith("*"):
            depth = len(l) - len(l.lstrip("*"))
            bullets.append((depth, l[depth:].strip()))
            section_of.append(cur_section)
    items: list[Item] = []
    stack: list[str] = []
    for i, (depth, raw) in enumerate(bullets):
        text, sources = clean(raw)
        stack = stack[: depth - 1] + [text]
        is_leaf = i + 1 >= len(bullets) or bullets[i + 1][0] <= depth
        if not is_leaf or not text:
            continue
        context = " > ".join(stack[:-1])
        full = f"{context} {section_of[i]} {text}"
        items.append(
            Item(
                date=d.isoformat(),
                section=section_of[i],
                context=context,
                text=text,
                sources=sources,
                topics={k: t.matches(full) for k, t in TOPICS.items()},
            )
        )
    return items


def _chunks(xs: list, n: int) -> Iterator[list]:
    for i in range(0, len(xs), n):
        yield xs[i : i + n]


def fetch_days(days: Iterable[date]) -> dict[date, str]:
    """Fetch raw wikitext for many days, 50 per request."""
    days = list(days)
    out: dict[date, str] = {}
    for chunk in _chunks(days, BATCH):
        params = {
            "action": "query",
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "titles": "|".join(page_title(d) for d in chunk),
            "format": "json",
            "formatversion": "2",
            "redirects": "1",
        }
        r = http.get(API, params, min_interval=1.0)
        js = r.json()
        for p in js.get("query", {}).get("pages", []):
            d = title_to_date(p["title"])
            if d is None or "missing" in p or "revisions" not in p:
                continue
            out[d] = p["revisions"][0]["slots"]["main"]["content"]
        log.info("wikipedia: %s..%s (%d pages)", chunk[0], chunk[-1], len(chunk))
    return out


def daterange(start: date, end: date) -> Iterator[date]:
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def backfill(start: date, end: date, data_dir: Path, *, refresh_days: int = 14) -> None:
    """Write data/wiki_items.jsonl (every item) and data/wiki_daily.json (counts).

    Existing days are kept unless within `refresh_days` of `end` (recent pages
    are still being edited).
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    items_path = data_dir / "wiki_items.jsonl"
    existing: dict[str, list[dict]] = {}
    if items_path.exists():
        for line in items_path.read_text().splitlines():
            it = json.loads(line)
            existing.setdefault(it["date"], []).append(it)
    cutoff = (end - timedelta(days=refresh_days)).isoformat()
    todo = [d for d in daterange(start, end) if d.isoformat() not in existing or d.isoformat() >= cutoff]
    log.info("wikipedia: %d days to fetch", len(todo))
    raw = fetch_days(todo)
    for d, wt in raw.items():
        existing[d.isoformat()] = [asdict(it) for it in parse_day(d, wt)]
    # Re-classify everything with the current patterns so edits to topics.py apply retroactively.
    for day_items in existing.values():
        for it in day_items:
            full = f"{it['context']} {it['section']} {it['text']}"
            it["topics"] = {k: t.matches(full) for k, t in TOPICS.items()}
    for day_items in existing.values():
        for it in day_items:
            it["topics_llm"] = labels.llm_topics(data_dir, " > ".join(x for x in (it["context"], it["text"]) if x))
    with items_path.open("w") as f:
        for day in sorted(existing):
            for it in existing[day]:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
    write_daily(existing, data_dir / "wiki_daily.json")
    write_recent(existing, data_dir / "wiki_recent.json", end)


def write_recent(by_day: dict[str, list[dict]], path: Path, end: date, days: int = 120) -> None:
    """Small file for the dashboard: every topic-matching item from the last `days` days."""
    since = (end - timedelta(days=days)).isoformat()
    recent = [
        {k: it.get(k) for k in ("date", "section", "context", "text", "sources", "topics", "topics_llm")}
        for day in sorted(by_day)
        if day >= since
        for it in by_day[day]
        if any(it["topics"].values()) or any((it.get("topics_llm") or {}).values())
    ]
    path.write_text(json.dumps(recent, ensure_ascii=False))


def write_daily(by_day: dict[str, list[dict]], path: Path) -> None:
    daily = {}
    for day in sorted(by_day):
        its = by_day[day]
        row = {"n": len(its)}
        for k in TOPICS:
            row[k] = sum(1 for it in its if it["topics"].get(k))
        for it in its:
            labels.add_llm_counts(row, it.get("topics_llm"))
        daily[day] = row
    path.write_text(
        json.dumps(
            {
                "meta": {
                    "source": "Wikipedia Portal:Current events (English)",
                    "unit": "count of leaf news items per day; topic columns are items matching the topic regex",
                    "topics": {k: t.pattern.pattern for k, t in TOPICS.items()},
                },
                "daily": daily,
            }
        )
    )
    log.info("wrote %s (%d days)", path, len(daily))
