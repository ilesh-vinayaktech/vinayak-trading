"""The extreme-move fade's signal and execution rejections: the +10% signal is known at the close of T and nothing later; a trade is rejected for a stated reason using only what is known before the T+1 open."""

import inspect

import numpy as np
import pandas as pd
import pytest

from algo.research import extreme_move as em


def _closes(n: int = 300, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2021-01-01", periods=n)
    c = 100 * np.cumprod(1 + rng.normal(0, 0.03, (n, 4)), axis=0)
    c[50, 0] *= 1.12  # a few real extreme days so the signal fires
    c[120, 2] *= 1.25
    return pd.DataFrame(c, index=dates, columns=[1, 2, 3, 4])


def test_the_signal_is_a_fixed_plus_10_percent_previous_day_return_with_the_boundary_kept_in():
    c = pd.DataFrame({1: [100.0, 110.0, 119.99, 131.0]})  # +10.00%, +9.08%, +9.18%
    assert em.extreme_up(c)[1].tolist() == [False, True, False, False]
    assert em.THRESHOLD == 0.10
    assert em.extreme_up(pd.DataFrame({1: [100.0, 109.99]}))[1].tolist() == [False, False]


@pytest.mark.parametrize("t", [60, 130, 250])
def test_the_signal_at_day_t_does_not_change_when_the_future_is_cut_or_scrambled(t):
    c = _closes()
    full = em.extreme_up(c).to_numpy()[: t + 1]
    cut = em.extreme_up(c.iloc[: t + 1]).to_numpy()
    np.testing.assert_array_equal(full, cut)
    bad = c.copy()
    bad.iloc[t + 1 :] = np.random.default_rng(1).uniform(1, 1000, bad.iloc[t + 1 :].shape)
    np.testing.assert_array_equal(full, em.extreme_up(bad).to_numpy()[: t + 1])
    assert (
        em.extreme_up(c).to_numpy()[50, 0] and em.extreme_up(c).to_numpy()[120, 2]
    )  # the control: the signal does fire on the planted days


def test_a_price_band_limit_is_recognised_to_the_tick_and_any_band_counts_when_it_is_unknown():
    prev = np.array([100.0, 100.0, 10.0, 100.0, 100.0])
    chg = np.array([0.0998, 0.0950, 0.0950, 0.0498, 0.2000])
    assert em.at_upper_limit(chg, prev, np.array([10.0, 10.0, 10.0, np.nan, np.nan])).tolist() == [
        True,
        False,
        True,
        True,
        True,
    ]
    assert em.at_upper_limit(chg, prev).tolist() == [
        True,
        False,
        True,
        True,
        True,
    ]  # unknown band: 5%, 10% and 20% all count
    assert em.at_upper_limit(np.array([0.0498]), np.array([100.0]), np.array([20.0])).tolist() == [
        False
    ]  # a known 20% band: +4.98% is not its limit


def _args(**over):
    base = dict(
        series_t=["EQ"], series_t1=["EQ"], open_t1=np.array([105.0]), low_t1=np.array([100.0]), high_t1=np.array([110.0]),
        close_t=np.array([111.0]), high_t=np.array([113.0]), prev_close_t=np.array([100.0]),
    )  # fmt: skip
    base.update(over)
    return base


def test_each_rejection_has_its_reason_and_the_first_one_wins():
    def r(**k):
        return int(em.rejection_reason(**_args(**k))[0])

    assert r() == em.OK
    assert r(series_t=["BE"]) == em.SERIES_T
    assert r(series_t1=["BZ"]) == em.SERIES_T1
    assert r(open_t1=np.array([0.0])) == em.BAD_OPEN
    assert r(open_t1=np.array([np.nan])) == em.BAD_OPEN
    assert r(open_t1=np.array([120.0])) == em.BAD_OPEN  # above its own day's high: a bad print
    assert (
        r(close_t=np.array([110.0]), high_t=np.array([110.0])) == em.LOCKED_CLOSE
    )  # +10% and closed on the high
    assert (
        r(close_t=np.array([110.0]), high_t=np.array([115.0])) == em.OK
    )  # +10% but off the high: not a lock
    assert (
        r(open_t1=np.array([111.0 * 1.2]), high_t1=np.array([140.0]), band_t1_pct=np.array([20.0]))
        == em.OPENS_AT_LIMIT
    )
    assert r(gsm_t1=np.array([True])) == em.GSM
    assert (
        r(series_t=["BE"], series_t1=["BZ"], open_t1=np.array([0.0])) == em.SERIES_T
    )  # the first listed reason wins
    assert set(em.REASONS) == {
        em.OK,
        em.SERIES_T,
        em.SERIES_T1,
        em.BAD_OPEN,
        em.LOCKED_CLOSE,
        em.OPENS_AT_LIMIT,
        em.GSM,
    }


def test_the_rejections_use_only_what_is_known_before_the_entry_open():
    params = set(inspect.signature(em.rejection_reason).parameters)
    assert not any(
        p in params for p in ("close_t1", "return_t1", "outcome")
    )  # nothing about how T+1 ended can be passed in
    base = em.rejection_reason(**_args())
    wider = em.rejection_reason(
        **_args(high_t1=np.array([130.0]), low_t1=np.array([90.0]))
    )  # a wider T+1 range that still contains the open changes nothing
    assert base.tolist() == wider.tolist()


def test_an_intraday_short_earns_the_fall_from_the_open_to_the_close():
    assert em.short_return(
        np.array([100.0, 100.0]), np.array([95.0, 103.0])
    ).tolist() == pytest.approx([0.05, -0.03])
