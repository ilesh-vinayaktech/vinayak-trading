from datetime import date, timedelta

from algo.market.rise_effect import HORIZON, MIN_DAYS, _rank_corr, _stats, effect

D0 = date(2026, 1, 1)


def series(n, step=1.0):
    return [(D0 + timedelta(days=i), 100 + step * i) for i in range(n)]


def test_too_few_matched_days_says_nothing():
    got = effect([(D0, 0.5)], series(40))
    assert (
        got["enough"] is False
        and got["days"] == 1
        and got["bands"] == []
        and got["rank_correlation"] is None
    )


def test_days_without_five_following_sessions_or_a_close_are_left_out():
    closes = series(60)
    scores = [(D0 + timedelta(days=i), 0.5) for i in range(60)] + [(D0 - timedelta(days=3), 0.5)]
    assert (
        effect(scores, closes)["days"] == 60 - HORIZON
    )  # the last five days and the day with no close are dropped


def test_bands_split_the_stocks_own_scores_and_a_rising_score_with_rising_returns_correlates():
    closes = [(D0 + timedelta(days=i), 100.0) for i in range(100)]
    # price rises 10% in the 5 sessions after the 20 highest-score days only
    scores, prices = [], list(closes)
    for i in range(80):
        scores.append((D0 + timedelta(days=i), i / 100))
    prices = [(d, 100.0 if i < 80 + 4 else 110.0) for i, (d, _) in enumerate(closes)]
    got = effect(scores, prices)
    assert got["enough"] and [b["band"] for b in got["bands"]] == [
        "top fifth",
        "middle",
        "bottom fifth",
    ]
    top, mid, bot = got["bands"]
    assert (
        top["n"] == 16
        and bot["n"] == 16
        and mid["n"] == 48
        and sum(b["n"] for b in got["bands"]) == got["days"]
    )
    assert top["mean"] > bot["mean"] and got["rank_correlation"] > 0 and top["from"] <= top["to"]


def test_helpers_handle_empty_ties_and_constant_sides():
    assert _stats([]) == {"n": 0, "mean": None, "up_share": None}
    assert _stats([0.1, -0.1, 0.1, 0.1]) == {"n": 4, "mean": 5.0, "up_share": 75.0}
    assert _rank_corr([1, 1, 1], [1, 2, 3]) is None
    assert _rank_corr([1, 2, 2, 3], [1, 2, 3, 4]) > 0.9
    assert _rank_corr([1, 2, 3], [3, 2, 1]) == -1.0
    assert MIN_DAYS == 30
