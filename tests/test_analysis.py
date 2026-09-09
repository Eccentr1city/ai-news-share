from ai_news_share import analysis


def test_rolling_share_pools_counts():
    daily = {
        "2020-01-01": {"n": 10, "ai": 1},
        "2020-01-02": {"n": 0, "ai": 0},
        "2020-01-04": {"n": 10, "ai": 3},  # 01-03 missing entirely
    }
    r = analysis.rolling_share(daily, "ai", k=7)
    assert r["2020-01-01"] == 0.1
    assert r["2020-01-02"] == 0.1  # empty day does not dilute
    assert r["2020-01-03"] == 0.1
    assert r["2020-01-04"] == 4 / 20


def test_rolling_share_window_drops_old():
    daily = {f"2020-01-0{i}": {"n": 10, "ai": (1 if i == 1 else 0)} for i in range(1, 10)}
    r = analysis.rolling_share(daily, "ai", k=3)
    assert r["2020-01-03"] == 1 / 30
    assert r["2020-01-04"] == 0.0


def test_compare_finds_first_covid_date_at_or_above_ai_level():
    covid = {"2019-12-01": 0.0, "2020-01-15": 0.05, "2020-02-01": 0.10, "2020-03-01": 0.60, "2020-03-15": 0.9}
    ai = {"2017-06-01": 0.01, "2026-09-01": 0.10}
    cmp = analysis.compare(ai, covid)
    assert cmp.match_date == "2020-02-01"
    assert cmp.covid_peak == ("2020-03-15", 0.9)
    # baseline mode: AI is 10x its 2017 baseline; Covid baseline window has no data -> None
    assert cmp.ai_baseline == 0.01
    assert cmp.match_date_norm is None


def test_compare_above_peak():
    covid = {"2020-03-15": 0.5}
    ai = {"2026-09-01": 0.7}
    cmp = analysis.compare(ai, covid)
    assert cmp.match_date is None
    assert "above" in cmp.notes[0]


def test_compare_match_on_window_start_is_not_a_date():
    covid = {"2019-12-01": 0.2, "2020-01-15": 0.3, "2020-03-15": 0.9}
    ai = {"2026-09-01": 0.1}
    cmp = analysis.compare(ai, covid)
    assert cmp.match_date is None
    assert "start of the window" in cmp.notes[0]


def test_fit_doubling_recovers_known_rate():
    import math
    # odds double every 10 days -> ln(odds) rises ln2/10 per day
    series = {}
    for i in range(40):
        d = analysis.date(2020, 1, 1) + analysis.timedelta(days=i)
        series[d.isoformat()] = math.log(0.01) + i * math.log(2) / 10
    fit = analysis.fit_doubling(series, "2020-01-01", "2020-02-09")
    assert abs(fit.doubling_days - 10) < 1e-6
    assert fit.r2 > 0.999
    assert fit.halving_days is None


def test_pooled_log_odds_handles_zero_counts():
    daily = {"2020-01-01": {"n": 100, "ai": 0}, "2020-01-02": {"n": 100, "ai": 10}}
    lo = analysis.pooled_log_odds(daily, "ai", k=1)
    assert lo["2020-01-01"] < -5  # finite, thanks to the pseudo-count
    assert abs(lo["2020-01-02"] - __import__("math").log(10.5 / 90.5)) < 1e-9
