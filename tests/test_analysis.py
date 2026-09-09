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
