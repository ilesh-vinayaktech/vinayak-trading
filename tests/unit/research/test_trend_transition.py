"""Trend-transition research: eligibility and features use only bars up to the signal session (proved by cutting and scrambling the future, and by a control that must FAIL when look-ahead is planted); barrier labels
handle success, failure, ambiguity, gaps, missing bars and the horizon edge exactly; walk-forward folds never overlap and are purged."""

import numpy as np
import pandas as pd
import pytest

from algo.research import trend_transition as tt

N_DAYS, N_STOCKS = 520, 8


def _panel(seed: int = 7):
    """Stocks that rise, fall, base and rise again: real eligible days exist for both strategies."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2019-01-01", periods=N_DAYS)
    closes = np.empty((N_DAYS, N_STOCKS))
    for j in range(N_STOCKS):
        phase = rng.integers(60, 140)
        drift = np.concatenate(
            [
                np.full(200 + phase // 2, 0.0012),
                np.full(130, -0.0055),
                np.full(70, 0.0),
                np.full(N_DAYS, 0.0030),
            ]
        )[:N_DAYS]
        closes[:, j] = 100 * np.cumprod(1 + drift + rng.normal(0, 0.012, N_DAYS))
    o = closes * (1 + rng.normal(0, 0.003, closes.shape))
    h = np.maximum(o, closes) * (1 + rng.uniform(0, 0.008, closes.shape))
    low = np.minimum(o, closes) * (1 - rng.uniform(0, 0.008, closes.shape))
    v = rng.uniform(1e5, 1e6, closes.shape)
    cols = list(range(101, 101 + N_STOCKS))

    def df(a):
        return pd.DataFrame(a, index=dates, columns=cols)

    return df(o), df(h), df(low), df(closes), df(v)


def _all_signals(p):
    o, h, low, c, v = p
    out = {"early": tt.early_eligible(h, low, c), "confirmed": tt.confirmed_eligible(h, low, c)}
    for grp, d in tt.features(o, h, low, c, v).items():
        out.update({f"{grp}.{k}": x for k, x in d.items()})
    out.update({f"base.{k}": x for k, x in tt.baseline_rules(o, h, low, c, v).items()})
    return out


def _same_through(a: dict, b: dict, t: int) -> list[str]:
    bad = []
    for k in a:
        x, y = (
            np.asarray(a[k].to_numpy(), dtype=float)[: t + 1],
            np.asarray(b[k].to_numpy(), dtype=float)[: t + 1],
        )
        if not np.allclose(x, y, rtol=1e-9, atol=1e-12, equal_nan=True):
            bad.append(k)
    return bad


def _upto(p, t):
    return tuple(x.iloc[: t + 1] for x in p)


@pytest.mark.parametrize("t", [150, 300, 450])
def test_every_eligibility_feature_and_baseline_at_session_t_ignores_the_future(t):
    p = _panel()
    full, cut = _all_signals(p), _all_signals(_upto(p, t))
    f = tt.features(*p)
    assert len(full) == 2 + len(f["E0"]) + len(f["E1"]) + 6  # nothing was skipped
    assert _same_through(full, cut, t) == []
    bad = tuple(x.copy() for x in p)
    rng = np.random.default_rng(5)
    for x in bad:
        x.iloc[t + 1 :] = rng.uniform(1, 1000, x.iloc[t + 1 :].shape)
    assert _same_through(full, _all_signals(bad), t) == []


def test_the_look_ahead_check_can_actually_fail():
    """Control: a feature that peeks ahead must be flagged by the very same comparison, or the tests above prove nothing."""
    p = _panel()
    t = 300

    def peek(panel):
        c = panel[3]
        return {"peek": c.shift(-1) / c - 1, "centered": c.rolling(5, center=True).mean() / c}

    assert set(_same_through(peek(p), peek(_upto(p, t)), t)) == {"peek", "centered"}


def test_early_and_confirmed_never_both_hold_and_the_early_rule_matches_an_independent_slow_version():
    o, h, low, c, v = _panel()
    e, f = tt.early_eligible(h, low, c), tt.confirmed_eligible(h, low, c)
    assert (
        int(e.sum().sum()) > 0 and int(f.sum().sum()) > 0
    )  # the control: the rules are not vacuous on this market
    assert not (e & f).to_numpy().any()
    for j in range(N_STOCKS):
        for t in (200, 260, 330, 400):
            hh, ll, cc = (
                h.iloc[: t + 1, j].to_numpy(),
                low.iloc[: t + 1, j].to_numpy(),
                c.iloc[: t + 1, j].to_numpy(),
            )
            l60, h120 = ll[-60:].min(), hh[-120:].max()
            ema50 = pd.Series(cc).ewm(span=50, adjust=False, min_periods=50).mean().iloc[-1]
            age_ok = (
                ll[-60:].argmin() <= 60 - 1 - tt.LOW_AGE
            )  # the 60-session low sits at least 10 sessions back
            ref = (
                l60 <= 0.75 * h120
                and age_ok
                and (hh[-20:].max() - ll[-20:].min()) / ll[-20:].min() <= 0.25
                and cc[-1] <= hh[-21:-1].max()
                and cc[-1] < ema50
                and cc[-1] <= 1.20 * l60
            )
            assert bool(e.iloc[t, j]) == bool(ref), (j, t)


def _path_panel():
    """One stock per scenario; the signal is session index 10 so the entry open is index 11 (= 100); barriers 108 / 96; session k is index 10 + k."""
    T = 60
    base = np.full((T, 8), 100.0)
    o, h, low, c = base.copy(), base * 1.01, base * 0.99, base.copy()
    h[16, 0] = 108.5  # col 0: success on session 6
    low[14, 1] = 95.5  # col 1: failure on session 4
    h[13, 2], low[13, 2] = 109.0, 95.0  # col 2: both barriers inside one candle (session 3)
    c[30, 3] = 103.0  # col 3: unresolved, closes session 20 at 103
    o[15, 4], h[15, 4], low[15, 4], c[15, 4] = (
        110.0,
        111.0,
        109.0,
        110.0,
    )  # col 4: gaps up through 108 at the open of session 5
    o[15, 5], h[15, 5], low[15, 5], c[15, 5] = 90.0, 91.0, 89.0, 90.0  # col 5: gaps down through 96
    h[13, 6] = np.nan  # col 6: a missing high before any barrier
    h[11, 7] = 108.2  # col 7: success on the entry day itself
    return o, h, low, c


def test_barrier_labels_success_failure_ambiguous_unresolved_gaps_and_missing_bars():
    o, h, low, c = _path_panel()
    r = tt.barrier_labels(o, h, low, c, np.full(8, 10), np.arange(8))
    assert r["code"].tolist() == [
        tt.SUCCESS,
        tt.FAILED,
        tt.AMBIGUOUS,
        tt.UNRESOLVED,
        tt.SUCCESS,
        tt.FAILED,
        tt.INCOMPLETE,
        tt.SUCCESS,
    ]
    assert r["k"][[0, 1, 2, 4, 5, 7]].tolist() == [6, 4, 3, 5, 5, 1]
    np.testing.assert_allclose(
        r["exit_ret"][[0, 1, 2]], [0.08, -0.04, -0.04]
    )  # ambiguous is booked at the adverse barrier, never the favourable one
    np.testing.assert_allclose(r["exit_ret"][3], 0.03)  # unresolved: the close of session 20
    np.testing.assert_allclose(r["exit_ret"][4], 0.10)  # a gap above the barrier fills at that open
    np.testing.assert_allclose(
        r["exit_ret"][5], -0.10
    )  # a gap below the adverse barrier fills at its open, worse than -4%
    assert r["best"][0] >= 0.085 - 1e-12 and r["worst"][1] <= -0.045 + 1e-12


def test_labels_look_only_at_sessions_after_the_signal_and_stop_at_the_exit():
    o, h, low, c = _path_panel()
    ti, sj = np.array([10, 10]), np.array([0, 1])
    base = tt.barrier_labels(o, h, low, c, ti, sj)
    h2, low2, o2 = h.copy(), low.copy(), o.copy()
    h2[:11, :] = 500.0  # the signal session and everything before it
    low2[:11, :] = 1.0
    o2[:10, :] = 7.0
    h2[17:, 0] = 900.0  # after the exit of column 0
    low2[15:, 1] = 1.0  # after the exit of column 1
    again = tt.barrier_labels(o2, h2, low2, c, ti, sj)
    assert again["code"].tolist() == base["code"].tolist() == [tt.SUCCESS, tt.FAILED]
    np.testing.assert_allclose(again["exit_ret"], base["exit_ret"])


def test_a_signal_too_close_to_the_end_or_with_no_entry_open_is_incomplete_not_guessed():
    o, h, low, c = _path_panel()
    o = o.copy()
    o[11, 0] = np.nan
    r = tt.barrier_labels(o, h, low, c, np.array([10, 45, 10]), np.array([0, 0, 1]))
    assert r["code"].tolist() == [
        tt.INCOMPLETE,
        tt.INCOMPLETE,
        tt.FAILED,
    ]  # no open; fewer than 20 sessions left; a normal one


def test_walk_forward_folds_never_overlap_and_are_purged_by_the_label_horizon():
    day_index = np.arange(1000)
    year = np.where(day_index < 400, 2020, np.where(day_index < 650, 2021, 2022))
    folds = tt.walk_forward_masks(year, day_index, {2021: 400, 2022: 650})
    for y, first in ((2021, 400), (2022, 650)):
        train, val = folds[y]
        assert not (train & val).any()
        assert (
            day_index[train].max() + 1 + tt.HORIZON < first
        )  # a training label looks at most 20 sessions beyond its entry day
        assert val.sum() == (year == y).sum()
    assert folds[2022][0].sum() > folds[2021][0].sum()  # later folds train on more history


def test_the_two_feature_groups_are_disjoint_and_carry_no_label():
    f = tt.features(*_panel())
    assert not set(f["E0"]) & set(f["E1"])
    assert not any(
        ("label" in k or "outcome" in k or "future" in k or "target" in k)
        for g in f.values()
        for k in g
    )
    assert {x.shape for g in f.values() for x in g.values()} == {(N_DAYS, N_STOCKS)}
