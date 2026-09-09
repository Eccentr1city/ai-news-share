# Is it February 2020 yet? — AI's share of the news vs. Covid's

People say "it's February 2020 for AI" to mean: the thing is real, the experts
are alarmed, and the public and political system have not yet woken up. This
repo makes that comparison quantitative. It tracks **what fraction of the top
news stories are about AI**, and puts that number on the same axis as **what
fraction were about Covid** through the winter and spring of 2020, so you can
read off statements like *"AI coverage today is where Covid coverage was on
January 24, 2020"* and see which political actions coincided with which level
of coverage.

Live dashboard: **https://eccentr1city.github.io/ai-news-share/** (updates daily via GitHub Actions).

## Quick start

```bash
uv sync
uv run ai-news-share backfill --no-gdelt   # ~75 s: Wikipedia, 2017 -> yesterday
uv run ai-news-share report --window 14    # the headline numbers in your terminal
uv run python -m http.server -d docs 8000  # open http://localhost:8000
```

Drop `--no-gdelt` to also pull the two GDELT series (slow: GDELT enforces one
request per 5 seconds and sometimes throttles harder; failures are non-fatal).

## How "top stories" is operationalized

There is no free, historical, US-only "top 100 stories" feed, so the project
measures three instruments that trade off breadth, prominence and history:

| Series | What is counted | Unit | History | Closest to |
|---|---|---|---|---|
| **Wikipedia Current Events** (primary) | Leaf items on `Portal:Current events/<day>`, an editorially curated list of the day's important news, ~15–40 items/day | share of items matching the AI regex, pooled over a rolling window | 2017 → today | "the top ~100 stories this week" |
| **GDELT TV** | CNN + Fox News + MSNBC airtime, via the Internet Archive TV News archive | % of 15-second clips mentioning AI (station average) | 2017 → recently | front-page *prominence* |
| **GDELT DOC** | Every US English online article GDELT monitors | % of articles matching the AI query | 2017 → today | total *volume* |
| **Google News Top Stories** | The ~35–70 headlines Google ranks as top stories right now | share of headlines | from the day you start collecting | the literal "top stories" framing, going forward |

The Covid comparison uses the same instrument and the same classifier
structure (a regex over item text plus its parent context), so both curves
are measured identically. Topic definitions live in
[`src/ai_news_share/topics.py`](src/ai_news_share/topics.py); every classified
item is written to `docs/data/wiki_items.jsonl` so the classifier can be
audited (`grep '"ai": true'`), and re-running `backfill` re-classifies history
with the current patterns.

## What the comparison does

1. Compute the rolling-window share (default 14 days) for AI now and for Covid
   in a window (default 2019-12-01 → 2020-06-30).
2. Find the first day Covid's share was at least AI's current share. That is
   the "it's ____ 2020" date.
3. Because AI had a nonzero baseline before the current boom and Covid had
   none, also do the same match after dividing each series by its own baseline
   (AI: 2017 mean; Covid: Jan–Nov 2019 mean).
4. Show US Covid milestones (first case, public health emergency, national
   emergency, CARES Act…) with the coverage level at each, so the question
   "how much coverage preceded which political action?" has a number.

## Honest caveats

- **Wikipedia's portal is global and event-shaped.** It records things that
  *happened* (a law passed, a model released, a court ruled), not debates or
  op-eds, and it covers the world, not the US. It under-counts slow-burn
  topics relative to US front pages. Its Covid curve is therefore probably
  *steeper* than a US front-page curve would be, and its AI level lower.
  Compare shapes and multiples, not just levels; use the GDELT series as a
  cross-check when they are available.
- **Keyword classifiers have edges.** The AI pattern is tuned for precision
  (it matches `AI` only as a capitalized token, plus named labs, models,
  people and concepts). Spot-check `wiki_recent.json` on the dashboard.
- **Small N.** A week of Wikipedia items is ~100–200, so a 7-day share moves
  in ~1% steps. The dashboard offers 7/14/28/56-day windows.
- **Structural difference.** Covid was one event with an exponential ramp over
  ~8 weeks and direct, visible harm to voters. AI is a slow burn with
  news-cycle spikes. Matching coverage levels says how *loud* the topic is
  relative to a known moment, not that politics will follow the same clock.

## Layout

```
src/ai_news_share/   wikipedia.py  gdelt.py  googlenews.py  topics.py  analysis.py  cli.py
docs/                index.html dashboard (GitHub Pages) + data/ (committed by the daily job)
tests/               parser, classifier and analysis tests (uv run pytest)
.github/workflows/   daily update: backfill + snapshot + report, commits docs/data
```
