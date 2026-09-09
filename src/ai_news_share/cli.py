"""Command line entry point.

  ai-news-share backfill [--since 2017-01-01] [--no-gdelt]   fetch/refresh all history
  ai-news-share gdelt [--budget-minutes 25] [--kind tv|doc]  slow, cached GDELT crawl (safe to re-run)
  ai-news-share nyt                                          NYT front page (needs NYT_API_KEY; resumable)
  ai-news-share llm [--status] [--sync]                      LLM topic labels (needs ANTHROPIC_API_KEY)
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

from . import analysis, gdelt, googlenews, llm_classify, nyt, wikipedia

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "docs" / "data"


def cmd_backfill(args) -> None:
    since = date.fromisoformat(args.since)
    end = date.today() - timedelta(days=1)  # today's Wikipedia page is still being written
    wikipedia.backfill(since, end, DATA)
    nyt.backfill(DATA, max(since, nyt.START))
    if not args.no_gdelt:
        cmd_gdelt(args)


def cmd_nyt(args) -> None:
    if not nyt.backfill(DATA, budget_s=60 * args.budget_minutes, refetch_from=args.refetch_from):
        sys.exit("NYT_API_KEY is not set (environment or .env); see README")


def cmd_gdelt(args) -> None:
    kinds = [args.kind] if getattr(args, "kind", None) else ["tv", "doc"]
    budget = 60 * float(getattr(args, "budget_minutes", 25)) / len(kinds)
    for kind in kinds:
        r = gdelt.crawl(kind, date.today(), DATA, budget_s=budget)
        if r["pending"]:
            logging.warning("GDELT %s: %d chunks still pending; re-run `ai-news-share gdelt` later", kind, r["pending"])


def cmd_llm(args) -> None:
    if getattr(args, "status", False):
        print(json.dumps(llm_classify.status(DATA), indent=1))
        return
    if getattr(args, "adjudicate", False):
        r = llm_classify.adjudicate(DATA, model=args.model, dry_run=args.dry_run)
        print(json.dumps(r))
        if r.get("relabeled"):
            wikipedia.backfill(date.today(), date.today() - timedelta(days=1), DATA)
            nyt.backfill(DATA, date.today(), date.today())
        return
    r = llm_classify.run(DATA, force_sync=getattr(args, "sync", False))
    print(json.dumps(r))
    if not r.get("skipped") and (r.get("ingested") or r.get("labeled_sync")):
        # Labels changed: rewrite the daily files without refetching anything.
        wikipedia.backfill(date.today(), date.today() - timedelta(days=1), DATA)
        nyt.backfill(DATA, date.today(), date.today())


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
    # Growth: doubling time of the odds (topic items : other items)
    print(f"  Doubling time of the odds, {k}-day window, least squares on ln(odds):")
    lo_cv = analysis.pooled_log_odds(daily, "covid", k)
    lo_ai = analysis.pooled_log_odds(daily, "ai", k)
    last = days[-1]
    for label, series, w in [
        ("Covid takeoff", lo_cv, analysis.COVID_TAKEOFF),
        ("AI since ChatGPT", lo_ai, ("2022-11-30", last)),
        ("AI last 2 years", lo_ai, ((date.fromisoformat(last) - timedelta(days=730)).isoformat(), last)),
        ("AI last year", lo_ai, ((date.fromisoformat(last) - timedelta(days=365)).isoformat(), last)),
    ]:
        f = analysis.fit_doubling(series, *w)
        if f is None:
            continue
        rate = f"doubles every {f.doubling_days:.0f} days" if f.doubling_days else f"halves every {f.halving_days:.0f} days" if f.halving_days else "flat"
        print(f"    {label:18s} {w[0]}..{w[1]}  {rate:26s} r²={f.r2:.2f}")


def cmd_update(args) -> None:
    cmd_backfill(args)
    cmd_llm(args)
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
    b.add_argument("--budget-minutes", type=float, default=25)
    b.set_defaults(fn=cmd_backfill)
    g = sub.add_parser("gdelt")
    g.add_argument("--kind", choices=["tv", "doc"])
    g.add_argument("--budget-minutes", type=float, default=25)
    g.set_defaults(fn=cmd_gdelt)
    n = sub.add_parser("nyt")
    n.add_argument("--budget-minutes", type=float, default=40)
    n.add_argument("--refetch-from", metavar="YYYY-MM", help="discard cached months from this month on")
    n.set_defaults(fn=cmd_nyt)
    l = sub.add_parser("llm")
    l.add_argument("--status", action="store_true")
    l.add_argument("--sync", action="store_true", help="label synchronously even if the backlog is large")
    l.add_argument("--adjudicate", action="store_true", help="re-label chunks with any AI positive using --model")
    l.add_argument("--model", default="claude-sonnet-5")
    l.add_argument("--dry-run", action="store_true")
    l.set_defaults(fn=cmd_llm)
    s = sub.add_parser("snapshot")
    s.set_defaults(fn=cmd_snapshot)
    r = sub.add_parser("report")
    r.add_argument("--window", type=int, default=7)
    r.set_defaults(fn=cmd_report)
    u = sub.add_parser("update")
    u.add_argument("--since", default="2017-01-01")
    u.add_argument("--no-gdelt", action="store_true")
    u.add_argument("--budget-minutes", type=float, default=25)
    u.add_argument("--window", type=int, default=7)
    u.set_defaults(fn=cmd_update)
    args = p.parse_args(argv)
    args.fn(args)
