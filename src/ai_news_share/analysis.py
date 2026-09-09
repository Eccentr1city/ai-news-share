"""Turn daily counts into the comparison the dashboard shows.

Core question: "AI coverage today is where Covid coverage was on ____."

Method:
  1. Rolling window (default 7 days). For count data (Wikipedia, Google News)
     the share is sum(topic items)/sum(all items) over the window, which is
     the right estimator for small daily N. For percentage data (GDELT) it is
     a plain moving average.
  2. Optionally express each series as a multiple of its own pre-period
     baseline (AI: median of its first year; Covid: median of the year before
     the window), because AI had a nonzero baseline and Covid had none.
  3. Find the first day in the Covid window (default 2019-12-01..2020-06-30)
     where Covid was at least as high as AI is now.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

# US political / institutional milestones for Covid, for reading the AI curve
# against "what level of coverage coincided with what action".
COVID_MILESTONES = [
    ("2020-01-21", "First confirmed US case"),
    ("2020-01-31", "HHS declares public health emergency"),
    ("2020-02-26", "First suspected US community spread"),
    ("2020-03-06", "Congress passes $8.3B emergency funding"),
    ("2020-03-11", "WHO declares pandemic; travel ban on Europe"),
    ("2020-03-13", "National emergency declared"),
    ("2020-03-19", "California statewide stay-at-home order"),
    ("2020-03-27", "CARES Act ($2.2T) signed"),
]

AI_MILESTONES = [
    ("2022-11-30", "ChatGPT released"),
    ("2023-03-14", "GPT-4 released"),
    ("2023-03-22", "FLI pause letter"),
    ("2023-05-16", "Altman testifies to Senate"),
    ("2023-10-30", "Biden AI executive order"),
    ("2023-11-01", "Bletchley Park summit"),
    ("2024-08-13", "EU AI Act enters into force"),
    ("2025-01-27", "DeepSeek market shock"),
    ("2025-09-29", "California SB 53 signed"),
]


def daterange(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def rolling_share(daily: dict[str, dict], topic: str, k: int = 7) -> dict[str, float | None]:
    """Windowed share for count data: sum(topic)/sum(n) over trailing k days."""
    if not daily:
        return {}
    days = sorted(daily)
    d0, d1 = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
    out: dict[str, float | None] = {}
    buf: list[tuple[int, int]] = []
    for d in daterange(d0, d1):
        row = daily.get(d.isoformat())
        buf.append((row[topic], row["n"]) if row else (0, 0))
        if len(buf) > k:
            buf.pop(0)
        n = sum(b[1] for b in buf)
        out[d.isoformat()] = (sum(b[0] for b in buf) / n) if n else None
    return out


def rolling_mean(series: dict[str, float], k: int = 7) -> dict[str, float | None]:
    """Trailing moving average for percentage data, tolerating gaps."""
    if not series:
        return {}
    days = sorted(series)
    d0, d1 = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
    out: dict[str, float | None] = {}
    buf: list[float] = []
    for d in daterange(d0, d1):
        v = series.get(d.isoformat())
        if v is not None:
            buf.append(v)
        if len(buf) > k:
            buf.pop(0)
        out[d.isoformat()] = sum(buf) / len(buf) if buf else None
    return out


def baseline(series: dict[str, float | None], start: str, end: str) -> float | None:
    """Mean level over a window (mean, not median: sparse count data is mostly zeros)."""
    vals = [v for d, v in series.items() if start <= d <= end and v is not None]
    return sum(vals) / len(vals) if vals else None


def first_reach(series: dict[str, float | None], level: float, start: str, end: str) -> str | None:
    for d in sorted(series):
        if start <= d <= end and series[d] is not None and series[d] >= level:
            return d
    return None


@dataclass
class Comparison:
    ai_date: str
    ai_now: float
    ai_now_norm: float | None
    covid_window: tuple[str, str]
    covid_peak: tuple[str, float]
    match_date: str | None  # level match
    match_date_norm: str | None  # multiple-of-baseline match
    ai_baseline: float | None
    covid_baseline: float | None
    notes: list[str] = field(default_factory=list)


def compare(
    ai: dict[str, float | None],
    covid: dict[str, float | None],
    *,
    covid_window: tuple[str, str] = ("2019-12-01", "2020-06-30"),
    ai_baseline_window: tuple[str, str] = ("2017-01-01", "2017-12-31"),
    covid_baseline_window: tuple[str, str] = ("2019-01-01", "2019-11-30"),
) -> Comparison | None:
    ai_days = [d for d in sorted(ai) if ai[d] is not None]
    if not ai_days:
        return None
    ai_date = ai_days[-1]
    ai_now = ai[ai_date]
    w0, w1 = covid_window
    win = {d: v for d, v in covid.items() if w0 <= d <= w1 and v is not None}
    if not win:
        return None
    peak_d = max(win, key=win.__getitem__)
    ai_b = baseline(ai, *ai_baseline_window)
    cv_b = baseline(covid, *covid_baseline_window)
    notes = []
    first_day = min(win)
    match = first_reach(win, ai_now, w0, w1)
    if match == first_day:  # Covid was already at least this loud when the window opens: not a date
        match = None
        notes.append(f"AI is at or below Covid's level at the start of the window ({first_day})")
    elif match is None:
        notes.append("AI is above Covid's peak in this window")
    match_norm = ai_now_norm = None
    if ai_b and cv_b:
        ai_now_norm = ai_now / ai_b
        match_norm = first_reach({d: v / cv_b for d, v in win.items()}, ai_now_norm, w0, w1)
        if match_norm == first_day:
            match_norm = None
    return Comparison(ai_date, ai_now, ai_now_norm, covid_window, (peak_d, win[peak_d]), match, match_norm, ai_b, cv_b, notes)
