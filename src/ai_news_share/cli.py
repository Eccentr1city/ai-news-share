"""Command line entry point.

  ai-news-share backfill [--since 2017-01-01] [--no-gdelt]   fetch/refresh all history
  ai-news-share snapshot                                     append today's Google News top stories
  ai-news-share report                                       print the headline comparison
  ai-news-share update                                       backfill + snapshot + report (what CI runs)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

from . import analysis, gdelt, googlenews, wikipedia

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "docs" / "data"


def cmd_backfill(args) -> None:
    since = date.fromisoformat(args.since)
    end = date.today() - timedelta(days=1)  # today's Wikipedia page is still being written
    wikipedia.backfill(since, end, DATA)
    if not args.no_gdelt:
        for kind in ("tv", "doc"):
            ok = gdelt.backfill(kind, max(since, gdelt.DOC_START), date.today(), DATA)
            if not ok:
                logging.warning("GDELT %s unavailable; dashboard falls back to Wikipedia only", kind)


def cmd_snapshot(args) -> None:
    googlenews.snapshot(DATA)


def load_daily() -> dict:
    p = DATA / "wiki_daily.json"
    return json.loads(p.read_text())["daily"] if p.exists() else {}


def cmd_report(args) -> None:
    daily = load_daily()
    if not daily:
        sys.exit("no data yet: run `ai-news-share backfill`")
    k = args.window
    ai = analysis.rolling_share(daily, "ai", k)
    cv = analysis.rolling_share(daily, "covid", k)
    cmp = analysis.compare(ai, cv)
    if cmp is None:
        sys.exit("not enough data for a comparison")
    pct = lambda x: f"{100 * x:.1f}%"  # noqa: E731
    print(f"Wikipedia Current Events, {k}-day window, as of {cmp.ai_date}")
    print(f"  AI share of news items now: {pct(cmp.ai_now)}")
    if cmp.ai_baseline:
        print(f"  AI 2017 baseline: {pct(cmp.ai_baseline)}  ->  {cmp.ai_now_norm:.1f}x baseline")
    print(f"  Covid peak in {cmp.covid_window[0]}..{cmp.covid_window[1]}: {pct(cmp.covid_peak[1])} on {cmp.covid_peak[0]}")
    if cmp.match_date:
        print(f"  Covid first reached today's AI level on: {cmp.match_date}")
    else:
        print(f"  {cmp.notes[0]}")
    if cmp.match_date_norm:
        print(f"  (as multiple of own baseline) on: {cmp.match_date_norm}")
    for d, label in analysis.COVID_MILESTONES:
        v = cv.get(d)
        print(f"    {d}  {pct(v) if v is not None else '  n/a'}  {label}")
    # Recent AI trend
    days = sorted(d for d in ai if ai[d] is not None)
    print("  AI share, last 8 weeks:")
    for d in days[-56::7]:
        print(f"    {d}  {pct(ai[d])}")


def cmd_update(args) -> None:
    cmd_backfill(args)
    cmd_snapshot(args)
    cmd_report(args)


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    p = argparse.ArgumentParser(prog="ai-news-share", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill")
    b.add_argument("--since", default="2017-01-01")
    b.add_argument("--no-gdelt", action="store_true")
    b.set_defaults(fn=cmd_backfill)
    s = sub.add_parser("snapshot")
    s.set_defaults(fn=cmd_snapshot)
    r = sub.add_parser("report")
    r.add_argument("--window", type=int, default=7)
    r.set_defaults(fn=cmd_report)
    u = sub.add_parser("update")
    u.add_argument("--since", default="2017-01-01")
    u.add_argument("--no-gdelt", action="store_true")
    u.add_argument("--window", type=int, default=7)
    u.set_defaults(fn=cmd_update)
    args = p.parse_args(argv)
    args.fn(args)
