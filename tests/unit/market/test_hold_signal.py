# ruff: noqa: E501
"""The hold signal, the pure parts: 31 OHLC-only features that never look ahead, a market-neutral target from the next open, ranks within the day, the buy / hold / sell state machine, and the frozen
numbers of the rule (docs: the module; evidence: scripts/study_hold_signal_folds.py). Stored models, the nightly run and the routes are in the integration tests."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from algo.market import hold_signal as hs


def make_bars(n_days: int = 330, n_stocks: int = 36, seed: int = 1) -> dict[int, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2019-01-01", periods=n_days)
    out = {}
    for iid in range(1, n_stocks + 1):
        c = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.02, n_days)))
        o = c * (1 + rng.normal(0, 0.004, n_days))
        h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.006, n_days)))
        lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.006, n_days)))
        out[iid] = pd.DataFrame({"o": o, "h": h, "l": lo, "c": c}, index=days)
    return out


class Stub:
    """A model that says the first feature (the 1-session return, in its own volatility units) is the chance."""

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        p = 1 / (1 + np.exp(-np.nan_to_num(X[:, 0])))
        return np.column_stack([1 - p, p])


def test_the_rule_is_the_frozen_one():
    assert len(hs.FEATURES) == 31 and len(set(hs.FEATURES)) == 31
    assert (hs.BUY_AT, hs.SELL_AT, hs.MAX_POSITIONS, hs.HORIZON) == (90.0, 20.0, 10, 5)
    assert hs.UNIVERSE_END == date(2024, 12, 31)
    assert hs.MODEL_PARAMS == {
        "max_depth": 4,
        "learning_rate": 0.05,
        "max_iter": 200,
        "min_samples_leaf": 500,
        "l2_regularization": 5.0,
        "random_state": 0,
    }


def test_the_model_for_a_day_was_trained_two_years_back_and_never_on_its_own_year():
    assert hs.train_end_for(date(2026, 11, 19)) == date(2024, 12, 31)
    assert hs.train_end_for(date(2022, 1, 3)) == date(2020, 12, 31)
    assert hs.train_end_for(date(2025, 12, 31)) == date(2023, 12, 31)


def test_every_feature_is_named_and_none_looks_ahead():
    bars = make_bars()
    full = hs.build_rows(bars, with_target=False)
    assert set(hs.FEATURES) <= set(full.columns)
    cut = bars[1].index[
        260
    ]  # wreck every bar after the cut: nothing known on or before it may move
    later = {k: v.copy() for k, v in bars.items()}
    for v in later.values():
        v.loc[v.index > cut] = v.loc[v.index > cut] * 3.7
    after = hs.build_rows(later, with_target=False)
    a = full[full["date"] <= cut].set_index(["iid", "date"]).sort_index()
    b = after[after["date"] <= cut].set_index(["iid", "date"]).sort_index()
    assert len(a) > 0
    pd.testing.assert_frame_equal(a[list(hs.FEATURES)], b[list(hs.FEATURES)], check_exact=False)


def test_the_target_is_the_return_from_the_next_open_less_the_days_median():
    bars = make_bars()
    rows = hs.build_rows(bars, with_target=True)
    r = rows[rows["iid"] == 3].iloc[40]
    b = bars[3]
    i = b.index.get_loc(r["date"])
    assert r["fwd"] == pytest.approx(b["c"].iloc[i + 5] / b["o"].iloc[i + 1] - 1)
    same_day = rows[rows["date"] == r["date"]]
    assert r["excess"] == pytest.approx(r["fwd"] - same_day["fwd"].median())
    assert rows["fwd"].notna().all()  # a row without a known future is not a training row


def test_the_newest_days_are_scored_though_their_future_is_not_known_yet():
    bars = make_bars()
    rows = hs.build_rows(bars, with_target=False)
    last = bars[1].index[-1]
    assert (rows["date"] == last).sum() == len(bars)  # the day just closed is there for every stock


def test_a_day_with_too_few_stocks_is_not_ranked():
    bars = make_bars(n_stocks=12)
    assert len(hs.build_rows(bars, with_target=False)) == 0
    assert len(hs.build_rows(bars, with_target=False, min_stocks=5)) > 0


def test_ranks_are_within_the_day_and_the_best_stock_of_the_day_is_100():
    rows = hs.build_rows(make_bars(), with_target=False)
    s = hs.score(Stub(), rows)
    assert {"day", "iid", "prob", "rank_pct"} <= set(s.columns)
    assert s["rank_pct"].between(0, 100).all() and s["prob"].between(0, 1).all()
    day = s[s["day"] == s["day"].max()]
    assert day["rank_pct"].max() == 100.0
    assert day.loc[day["prob"].idxmax(), "rank_pct"] == 100.0
    assert (day.groupby("iid").size() == 1).all()


def test_the_state_machine_buys_when_flat_holds_until_the_rank_falls_and_sells_once():
    n = 6
    in_pos = np.zeros(n, dtype=bool)
    entry = np.array([None] * n, dtype=object)
    rank = np.array([95.0, 95.0, 50.0, 10.0, 91.0, 89.9])
    act, in_pos, entry = hs.advance(rank, in_pos, entry, date(2026, 1, 5))
    assert list(act) == [
        "BUY",
        "BUY",
        "NONE",
        "NONE",
        "BUY",
        "NONE",
    ]  # buy at 90 and above, flat stocks only
    assert list(in_pos) == [True, True, False, False, True, False]
    assert all(e == date(2026, 1, 5) for e in entry[in_pos])
    rank2 = np.array([95.0, 50.0, 50.0, 10.0, 20.0, 99.0])
    act, in_pos, entry = hs.advance(rank2, in_pos, entry, date(2026, 1, 6))
    assert list(act) == [
        "HOLD",
        "HOLD",
        "NONE",
        "NONE",
        "SELL",
        "BUY",
    ]  # held stocks stay while the rank is above 20; 20 and below sells; a flat stock at 99 buys
    assert list(in_pos) == [True, True, False, False, False, True]
    assert (
        entry[0] == date(2026, 1, 5) and entry[4] is None and entry[5] == date(2026, 1, 6)
    )  # the entry day is kept while held and cleared on a sell


def test_a_held_stock_is_never_bought_again():
    act, in_pos, entry = hs.advance(
        np.array([99.0]),
        np.array([True]),
        np.array([date(2026, 1, 2)], dtype=object),
        date(2026, 1, 9),
    )
    assert list(act) == ["HOLD"] and entry[0] == date(2026, 1, 2)


def test_the_fit_runs_and_is_deterministic():
    bars = make_bars(n_days=420, n_stocks=36)
    rows = hs.build_rows(bars, with_target=True)
    X, y = hs.training_set(rows, date(2020, 12, 31))
    assert len(X) == len(y) > 0 and set(np.unique(y)) <= {0, 1}
    m1, m2 = hs.fit(X, y, min_leaf=20), hs.fit(X, y, min_leaf=20)
    assert np.array_equal(m1.predict_proba(X[:200]), m2.predict_proba(X[:200]))


def test_a_training_set_holds_nothing_after_its_train_end():
    rows = hs.build_rows(make_bars(n_days=420), with_target=True)
    cut = date(2020, 3, 31)
    X, y = hs.training_set(rows, cut)
    kept = rows[rows["date"] <= pd.Timestamp(cut)]
    assert len(X) == len(kept)
    assert kept["date"].max() <= pd.Timestamp(cut)
