"""Look-ahead tests for the next-session studies: every feature known at the close of day T must not change when the future changes, the next-open entry must come from day T+1 only, a bad or missing
open must be NaN (never repaired), and corporate actions must be handled on the right session. Executable proof, not code inspection."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from algo.research import next_session_features as nf

N_DAYS, N_STOCKS = 320, 3


def _panel(seed: int = 0):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2021-01-01", periods=N_DAYS)
    cols = [101, 102, 103]
    c = np.empty((N_DAYS, N_STOCKS))
    o = np.empty_like(c)
    prev = np.full(N_STOCKS, 100.0)
    for t in range(N_DAYS):
        o[t] = prev * (1 + rng.normal(0, 0.01, N_STOCKS))
        c[t] = o[t] * (1 + rng.normal(0, 0.015, N_STOCKS))
        prev = c[t]
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.01, c.shape))
    low = np.minimum(o, c) * (1 - rng.uniform(0, 0.01, c.shape))
    v = rng.uniform(1e5, 1e6, c.shape)

    def df(a):
        return pd.DataFrame(a, index=dates, columns=cols)

    nifty = pd.Series(18000 * np.cumprod(1 + rng.normal(0.0003, 0.008, N_DAYS)), index=dates)
    vix = pd.Series(15 + np.cumsum(rng.normal(0, 0.3, N_DAYS)), index=dates).clip(lower=8)
    sec = pd.Series(["IT", "IT", np.nan], index=cols, dtype=object)
    return df(o), df(h), df(low), df(c), df(v), df(v * 0.4), nifty, vix, sec


def _arr(x) -> np.ndarray:
    return np.asarray(x.to_numpy() if isinstance(x, pd.DataFrame) else x, dtype=float)


def _upto(p, t):
    o, h, low, c, v, dq, nifty, vix, sec = p
    return (
        o.iloc[: t + 1],
        h.iloc[: t + 1],
        low.iloc[: t + 1],
        c.iloc[: t + 1],
        v.iloc[: t + 1],
        dq.iloc[: t + 1],
        nifty.iloc[: t + 1],
        vix.iloc[: t + 1],
        sec,
    )


def _assert_same_through(f_full, f_cut, aux_full, aux_cut, t):
    n = 0
    for g in nf.GROUP_ORDER:
        assert set(f_full[g]) == set(f_cut[g])
        for name in f_full[g]:
            a, b = _arr(f_full[g][name])[: t + 1], _arr(f_cut[g][name])[: t + 1]
            np.testing.assert_allclose(
                a,
                b,
                rtol=1e-9,
                atol=1e-12,
                equal_nan=True,
                err_msg=f"{g}.{name} at T={t} depends on the future",
            )
            n += 1
    np.testing.assert_allclose(
        _arr(aux_full["turn"])[: t + 1], _arr(aux_cut["turn"])[: t + 1], equal_nan=True
    )  # the liquidity filter is trailing too
    assert n == 51  # every one of the 51 features was compared


@pytest.mark.parametrize("t", [80, 150, 260, 318])
def test_every_feature_at_day_t_is_identical_when_the_data_is_cut_at_t(t):
    p = _panel()
    f_full, aux_full = nf.build_features(*p)
    f_cut, aux_cut = nf.build_features(*_upto(p, t))
    _assert_same_through(f_full, f_cut, aux_full, aux_cut, t)


def test_scrambling_every_bar_after_t_changes_no_feature_at_or_before_t():
    p = _panel()
    t = 200
    o, h, low, c, v, dq, nifty, vix = (x.copy() for x in p[:8])
    rng = np.random.default_rng(99)
    for frame in (o, h, low, c, v, dq):
        frame.iloc[t + 1 :] = rng.uniform(1, 1000, frame.iloc[t + 1 :].shape)
    nifty.iloc[t + 1 :] = rng.uniform(1000, 30000, len(nifty) - t - 1)
    vix.iloc[t + 1 :] = rng.uniform(5, 80, len(vix) - t - 1)
    f_full, aux_full = nf.build_features(*p)
    f_bad, aux_bad = nf.build_features(o, h, low, c, v, dq, nifty, vix, p[8])
    _assert_same_through(f_full, f_bad, aux_full, aux_bad, t)


def test_the_comparison_can_actually_see_look_ahead():
    """Control: the TARGET (next session's return) does depend on day t+1, so the same kind of comparison must flag it. If this ever passes by accident the tests above prove nothing."""
    c = _panel()[3]
    t = 150
    c2 = c.copy()
    c2.iloc[t + 1] = c2.iloc[t + 1] * 1.2
    div = np.zeros(c.shape, dtype=np.float32)
    a, b = nf.next_session_return(c, div), nf.next_session_return(c2, div)
    assert not np.allclose(a[t], b[t])
    np.testing.assert_allclose(a[: t - 1], b[: t - 1], equal_nan=True)


def test_the_price_only_set_has_nine_features_and_none_of_them_is_sector_or_market_data():
    f, _ = nf.build_features(*_panel())
    assert sorted(f["A"]) == sorted(
        ["ret1", "ret2", "ret3", "ret5", "ret10", "gap", "intraday", "gap_reversal", "streak"]
    )
    assert not set(f["A"]) & (set(f["F"]) | set(f["E"]))
    # group F (sector) is NaN for a stock with no classification: nothing is invented for it
    assert np.isnan(_arr(f["F"]["sec_r5"])[:, 2]).all()


def test_the_next_open_entry_is_taken_from_the_next_session_only():
    o, h, low, c = _panel()[:4]
    t = 120
    e = nf.next_open_entry(o, h, low, c)
    assert e["entry"][t, 0] == pytest.approx(o.iloc[t + 1, 0])
    assert e["overnight"][t, 0] == pytest.approx(o.iloc[t + 1, 0] / c.iloc[t, 0] - 1)
    assert e["ret1"][t, 0] == pytest.approx(c.iloc[t + 1, 0] / o.iloc[t + 1, 0] - 1)
    assert e["ret2"][t, 0] == pytest.approx(c.iloc[t + 2, 0] / o.iloc[t + 1, 0] - 1)
    assert e["ret3"][t, 0] == pytest.approx(c.iloc[t + 3, 0] / o.iloc[t + 1, 0] - 1)
    assert e["mfe2"][t, 0] == pytest.approx(
        max(h.iloc[t + 1, 0], h.iloc[t + 2, 0]) / o.iloc[t + 1, 0] - 1
    )
    assert e["mae3"][t, 0] == pytest.approx(min(low.iloc[t + 1 : t + 4, 0]) / o.iloc[t + 1, 0] - 1)
    # nothing at or before day t, and nothing after t+1's open, can move the entry
    o2, c2, h2 = o.copy(), c.copy(), h.copy()
    o2.iloc[t, 0] *= 1.5
    o2.iloc[t + 2 :, 0] *= 1.5
    c2.iloc[t + 1 :, 0] *= 1.1
    h2.iloc[t + 1, 0] *= 1.05
    assert nf.next_open_entry(o2, h2, low, c2)["entry"][t, 0] == pytest.approx(e["entry"][t, 0])


def test_a_missing_or_invalid_next_open_is_nan_and_never_repaired():
    o, h, low, c = (x.copy() for x in _panel()[:4])
    t = 100
    o.iloc[t + 1, 0] = 0.0  # zero print
    o.iloc[t + 1, 1] = h.iloc[t + 1, 1] * 1.5  # an open above the day's own high: a bad print
    o.iloc[t + 1, 2] = np.nan  # no open at all
    e = nf.next_open_entry(o, h, low, c)
    assert np.isnan(e["entry"][t, :]).all() and not e["valid"][t, :].any()
    assert np.isnan(e["ret1"][t, :]).all() and np.isnan(e["overnight"][t, :]).all()
    assert e["valid"][t + 1, :].all()  # the neighbours are untouched
    c.iloc[t + 5, 0] = (
        np.nan
    )  # a missing close inside the horizon: that horizon is NaN, shorter ones are not
    e = nf.next_open_entry(o, h, low, c)
    assert (
        not np.isnan(e["ret1"][t + 3, 0])
        and np.isnan(e["ret1"][t + 4, 0])
        and np.isnan(e["ret2"][t + 3, 0])
        and np.isnan(e["ret3"][t + 2, 0])
    )


def test_corporate_actions_drop_the_right_window_and_add_the_dividend_to_the_ex_date_session():
    c = _panel()[3]
    idx = c.index.values
    acts = [
        (101, c.index[100].date(), "split", None),
        (102, c.index[150].date(), "dividend", 5.0),
        (103, date(2021, 7, 3), "bonus", None),  # a Saturday: maps to the next session
        (999, c.index[100].date(), "split", None),  # a stock not in the panel: ignored
        (101, c.index[10].date(), "memo", None),  # an unknown kind: ignored
        (101, date(2030, 1, 1), "split", None),  # after the last session: ignored
        (102, c.index[160].date(), "dividend", None),  # a dividend with no amount: ignored
    ]
    div, bad = nf.corporate_action_masks(idx, list(c.columns), acts)
    assert bad[100 - 25 : 100 + 22, 0].all() and not bad[100 - 26, 0] and not bad[100 + 22, 0]
    assert not bad[:, 1].any() and div[150, 1] == 5.0 and div.sum() == 5.0
    j = int(np.searchsorted(idx, np.datetime64(date(2021, 7, 3))))
    assert bad[j, 2] and not bad[j - 26, 2]
    r = nf.next_session_return(c, div)
    # the dividend belongs to the return INTO the ex-date session: the row decided on day 149 (earned on day 150), not row 150
    assert r[149, 1] == pytest.approx((c.iloc[150, 1] + 5.0) / c.iloc[149, 1] - 1)
    assert r[150, 1] == pytest.approx(c.iloc[151, 1] / c.iloc[150, 1] - 1)
    assert np.isnan(r[-1, 0])  # the last session has no next session


def test_the_flat_band_and_exclusion_windows_are_frozen():
    assert nf.FLAT == 0.001
    assert (nf.WINDOW_BEFORE, nf.WINDOW_AFTER) == (25, 22)


@pytest.mark.parametrize(
    "script", ["study_volatility.py", "study_next_session.py", "study_reversal.py", "study_fade.py", "study_trend_transition.py"]
)
def test_the_recent_studies_cut_their_price_queries_before_the_holdout_and_have_no_final_switch(
    script,
):
    """The protected holdout is 2025-01-01..2026-11-13 (config/research_holdout.json); the owner's brief said 2024+. These studies stop at 2024-01-01 inside the SQL and offer no way to read past it."""
    from pathlib import Path

    text = (Path(__file__).resolve().parents[3] / "scripts" / script).read_text()
    assert 'END = "2024-01-01"' in text or "< '2024-01-01'" in text
    assert "< %s" in text or "< '2024-01-01'" in text  # the bound is in the query itself
    assert 'add_argument("--final"' not in text  # no switch that evaluates the held-out years
