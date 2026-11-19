# ruff: noqa: E501
"""Rise odds, the pure parts: the features never look ahead, the label is relative to the median stock, a training row ends well before the day its model may score, and a day's
scores are ranked within that day. (The stored models and the nightly run are in tests/integration/market/test_rise_odds.py.)"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from algo.market import rise_odds as ro


def make_panel(
    n_days: int = 320, n_stocks: int = 25, seed: int = 1, volume: float = 2e6
) -> ro.Panel:
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2025-01-01", periods=n_days).date
    steps = rng.normal(0.0005, 0.02, size=(n_days, n_stocks))
    close = pd.DataFrame(
        100 * np.exp(np.cumsum(steps, axis=0)), index=days, columns=range(1, n_stocks + 1)
    ).astype("float32")
    vol = pd.DataFrame(
        volume * (1 + 0.3 * rng.random((n_days, n_stocks))), index=days, columns=close.columns
    ).astype("float32")
    return ro.Panel(
        high=(close * 1.01).astype("float32"),
        low=(close * 0.99).astype("float32"),
        close=close,
        volume=vol,
        delivery=(vol * (0.4 + 0.3 * rng.random((n_days, n_stocks)))).astype("float32"),
    )


class Stub:
    """A model that says the first feature (the 1-day return) is the chance."""

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        p = 1 / (1 + np.exp(-X[:, 0] * 10))
        return np.column_stack([1 - p, p])


def test_the_features_are_all_named_and_none_looks_ahead():
    p = make_panel()
    f = ro.features(p)
    assert len(ro.FEATURES) == 21 and set(ro.FEATURES) <= set(f) and set(ro.OWN_FEATURES) <= set(f)
    assert (
        "rs20" not in ro.OWN_FEATURES and "rs60" not in ro.OWN_FEATURES
    )  # the own-direction model sees only the stock's own history
    cut = 250  # change every bar after day 250: nothing known on day 250 or before may move
    later = ro.Panel(*(df.copy() for df in (p.high, p.low, p.close, p.volume, p.delivery)))
    for df in (later.high, later.low, later.close, later.volume, later.delivery):
        df.iloc[cut + 1 :] = df.iloc[cut + 1 :] * 3
    g = ro.features(later)
    for name in f:
        pd.testing.assert_frame_equal(
            f[name].iloc[: cut + 1], g[name].iloc[: cut + 1], check_exact=False, obj=name
        )


def test_a_thinly_traded_stock_is_not_liquid_and_the_rest_are():
    p = make_panel()
    p.volume.iloc[:, 0] = 100  # stock 1 trades about Rs 1 lakh a day
    ok = ro.liquid(p)
    assert not ok.iloc[-1, 0] and ok.iloc[-1, 1:].all()


def test_the_label_is_relative_to_the_median_liquid_stock_and_unknown_at_the_end_and_near_a_split():
    p = make_panel()
    split = (3, p.close.index[200])
    ex = ro.excess(
        p, [split, (999, p.close.index[100])]
    )  # a split recorded for a stock that is not in the panel changes nothing
    assert ex.iloc[-ro.HORIZON :].isna().all().all()  # the last 5 sessions have no future yet
    assert (
        ex.iloc[150:250].median(axis=1).abs().max() < 0.02
    )  # about zero: the median stock beats itself half the time
    assert (
        ex.iloc[131:206, 2].isna().all()
    )  # stock 3 from 70 sessions before its split (the longest look-back) to 5 after: not comparable
    assert (
        ex.iloc[40:125, 2].notna().all() and ex.iloc[210:300, 2].notna().all()
    )  # and comparable either side


def test_training_rows_end_well_before_the_day_the_model_may_score_from():
    p = make_panel()
    f = ro.features(p)
    train_end = date(2025, 11, 3)
    X, y = ro.training_set(p, f, [], train_end)
    assert X.shape[1] == 21 and set(np.unique(y)) <= {0, 1} and len(X) == len(y) > 500
    gap = timedelta(days=2 * ro.HORIZON + 10)
    last_day = max(d for d in p.close.index if d < train_end - gap)
    n_days_allowed = sum(1 for d in p.close.index if d < train_end - gap)
    assert len(X) <= n_days_allowed * p.close.shape[1]  # no row from a day on or after the cut-off
    assert pd.Timestamp(last_day).date() < train_end - gap + timedelta(days=1)
    X2, _ = ro.training_set(p, f, [], date(2025, 1, 2))
    assert len(X2) == 0  # nothing before the first bars


def test_scores_are_made_for_the_days_asked_ranked_within_each_day():
    p = make_panel()
    f = ro.features(p)
    days = [p.close.index[-2], p.close.index[-1]]
    s = ro.score_range(Stub(), p, f, days)
    assert set(pd.to_datetime(s["day"]).dt.date) == set(days)
    assert s["prob"].between(0, 1).all() and s["pct"].between(0, 100).all()
    one = s[pd.to_datetime(s["day"]).dt.date == days[-1]]
    assert one["pct"].max() == pytest.approx(100) and one["pct"].min() > 0
    best = one.loc[one["prob"].idxmax()]
    assert best["pct"] == pytest.approx(100)  # the highest chance is the top rank
    assert ro.score_range(
        Stub(), p, f, [date(2030, 1, 1)]
    ).empty  # a day with no bars scores nothing


def test_a_thin_stock_gets_no_score():
    p = make_panel()
    p.volume.iloc[:, 0] = 100
    s = ro.score_range(Stub(), p, ro.features(p), [p.close.index[-1]])
    assert 1 not in set(s["iid"])


def test_fit_learns_something_on_a_planted_pattern_and_is_deterministic():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(4000, 21)).astype("float32")
    y = (X[:, 5] + 0.3 * rng.normal(size=4000) > 0).astype(
        np.int8
    )  # the 6th feature drives the label
    a, b = ro.fit(X, y, min_leaf=20), ro.fit(X, y, min_leaf=20)
    pa = a.predict_proba(X)[:, 1]
    assert np.corrcoef(pa, X[:, 5])[0, 1] > 0.6
    assert np.allclose(pa, b.predict_proba(X)[:, 1])  # same data, same model


def test_the_own_direction_target_is_the_plain_return_and_the_relative_one_is_less_the_median_stock():
    p = make_panel()
    rel, up = ro.target(p, [], "rel"), ro.target(p, [], "up")
    plain = ro.forward_return(p, [])
    pd.testing.assert_frame_equal(up, plain)
    assert up.iloc[-ro.HORIZON :].isna().all().all()  # the last 5 sessions have no future yet
    assert (
        up.iloc[100:200].median(axis=1) - rel.iloc[100:200].median(axis=1)
    ).abs().max() > 0  # a market drift is in the plain return and out of the relative one
    assert (
        ro.forward_return(p, [(3, p.close.index[200])]).iloc[150:206, 2].isna().all()
    )  # near a split: not comparable


def test_each_kind_is_fitted_on_its_own_features_and_names_its_versions_apart():
    p = make_panel()
    f = ro.features(p)
    X_rel, y_rel = ro.training_set(p, f, [], date(2025, 11, 3), kind="rel")
    X_up, y_up = ro.training_set(p, f, [], date(2025, 11, 3), kind="up")
    assert (
        X_rel.shape[1] == len(ro.FEATURES)
        and X_up.shape[1] == len(ro.OWN_FEATURES)
        and len(y_rel) == len(y_up) > 500
    )
    assert y_up.mean() != y_rel.mean() or not np.array_equal(y_up, y_rel)  # not the same question
    assert (
        ro.version_of(date(2026, 1, 1)) == "h5-2026-01-01"
        and ro.version_of(date(2026, 1, 1), kind="up") == "h5up-2026-01-01"
    )
    days = [p.close.index[-1]]
    assert len(ro.score_range(Stub(), p, f, days, kind="up")) == len(
        ro.score_range(Stub(), p, f, days, kind="rel")
    )  # the same stocks are scored either way
