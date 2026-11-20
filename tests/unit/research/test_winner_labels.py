"""Labels for the early-large-upside research (V2 spec, targets A, B, C and the excursion fields).

Signal after the close of session 0; entry = open of session 1; the window is sessions 1..10 (exit close = close of session 10).
All panels here are days x stocks. A flat panel is 100.0 everywhere; each test bends one day.
"""

from typing import Any

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from algo.research.winner_labels import (
    AMBIGUOUS,
    FAILURE,
    NO_EVENT,
    SUCCESS,
    WinnerLabels,
    winner_labels,
)

Panel = dict[str, np.ndarray[Any, Any]]

DAYS = 14


def flat(n: int = DAYS, stocks: int = 1) -> Panel:
    return {k: np.full((n, stocks), 100.0) for k in "ohlc"}


def lab(p: Panel, **kw: Any) -> WinnerLabels:
    return winner_labels(p["o"], p["h"], p["l"], p["c"], **kw)


def test_success_at_the_target_price_on_day_3() -> None:
    p = flat()
    p["h"][3, 0] = 111.0
    r = lab(p)
    assert r.valid[0, 0] and r.outcome[0, 0] == SUCCESS
    assert r.exit_session[0, 0] == 3
    assert np.isclose(r.exit_return[0, 0], 0.10)  # filled at the barrier, not at the high


def test_failure_at_the_stop_price_on_day_2() -> None:
    p = flat()
    p["l"][2, 0] = 94.0
    r = lab(p)
    assert r.outcome[0, 0] == FAILURE and r.exit_session[0, 0] == 2
    assert np.isclose(r.exit_return[0, 0], -0.05)


def test_no_event_exits_at_the_close_of_session_10() -> None:
    p = flat()
    p["c"][10, 0] = 103.0
    r = lab(p)
    assert r.outcome[0, 0] == NO_EVENT and r.exit_session[0, 0] == 10
    assert np.isclose(r.exit_return[0, 0], 0.03)


def test_both_barriers_in_one_candle_is_ambiguous_and_never_ordered() -> None:
    p = flat()
    p["h"][4, 0], p["l"][4, 0] = 112.0, 94.0
    r = lab(p)
    assert r.outcome[0, 0] == AMBIGUOUS and np.isnan(r.exit_return[0, 0])
    assert not (
        r.outcome[0, 0] == SUCCESS
    )  # the conservative primary label counts it as no success


def test_entry_day_touching_both_barriers_is_ambiguous() -> None:
    p = flat()
    p["h"][1, 0], p["l"][1, 0] = 112.0, 94.0
    assert lab(p).outcome[0, 0] == AMBIGUOUS


def test_gap_above_the_target_exits_at_the_open_not_the_barrier() -> None:
    p = flat()
    p["o"][5, 0], p["h"][5, 0], p["l"][5, 0] = 115.0, 116.0, 114.0
    r = lab(p)
    assert r.outcome[0, 0] == SUCCESS and r.exit_session[0, 0] == 5
    assert np.isclose(r.exit_return[0, 0], 0.15)


def test_gap_below_the_stop_exits_at_the_open_not_the_barrier() -> None:
    p = flat()
    p["o"][5, 0], p["h"][5, 0], p["l"][5, 0] = 90.0, 91.0, 89.0
    r = lab(p)
    assert r.outcome[0, 0] == FAILURE and np.isclose(r.exit_return[0, 0], -0.10)


def test_gap_open_above_target_wins_even_if_the_same_day_low_breaks_the_stop() -> None:
    p = flat()
    p["o"][5, 0], p["h"][5, 0], p["l"][5, 0] = 115.0, 118.0, 94.0
    r = lab(p)
    assert r.outcome[0, 0] == SUCCESS and np.isclose(
        r.exit_return[0, 0], 0.15
    )  # the open was executable


def test_first_barrier_wins_when_they_come_on_different_days() -> None:
    p = flat()
    p["l"][2, 0] = 94.0
    p["h"][6, 0] = 120.0
    r = lab(p)
    assert r.outcome[0, 0] == FAILURE and r.exit_session[0, 0] == 2


def test_entry_is_the_next_open_so_barriers_follow_it() -> None:
    p = flat()
    p["o"][1:, 0] = 120.0  # the stock gaps up at the entry open: the barriers are 132 and 114
    p["h"][1:, 0] = 120.0
    p["l"][1:, 0] = 120.0
    p["c"][1:, 0] = 120.0
    p["h"][3, 0] = 131.0  # under 132
    r = lab(p)
    assert r.outcome[0, 0] == NO_EVENT
    p["h"][3, 0] = 133.0
    assert lab(p).outcome[0, 0] == SUCCESS


def test_target_a_is_close_to_close_and_target_b_is_next_open_to_close() -> None:
    p = flat()
    p["c"][10, 0] = 110.0
    p["o"][1, 0] = 106.0  # gap at the entry: the move left after the open is 110/106 - 1 = 3.8%
    r = lab(p)
    assert r.target_a[0, 0]
    assert np.isclose(r.ret_exec[0, 0], 110.0 / 106.0 - 1)
    assert not r.target_b_5[0, 0] and not r.target_b_8[0, 0] and not r.target_b_10[0, 0]


def test_target_b_thresholds_are_independent() -> None:
    p = flat()
    p["c"][10, 0] = 109.0
    r = lab(p)
    assert r.target_b_5[0, 0] and r.target_b_8[0, 0] and not r.target_b_10[0, 0]
    assert not r.target_a[0, 0]


def test_excursions_and_sessions_to_levels() -> None:
    p = flat()
    p["h"][2, 0], p["h"][4, 0], p["h"][7, 0] = 105.0, 108.0, 111.0
    p["l"][3, 0] = 96.0
    p["l"][8, 0] = 94.0
    p["c"][6, 0], p["c"][9, 0] = 104.0, 97.0
    r = lab(p)
    assert np.isclose(r.mfe[0, 0], 0.11) and np.isclose(r.mae[0, 0], -0.06)
    assert np.isclose(r.max_ret[0, 0], 0.04) and np.isclose(r.min_ret[0, 0], -0.03)
    assert (r.s5[0, 0], r.s8[0, 0], r.s10[0, 0], r.sm5[0, 0]) == (2, 4, 7, 8)


def test_sessions_to_a_level_never_reached_is_nan() -> None:
    r = lab(flat())
    assert np.isnan(r.s5[0, 0]) and np.isnan(r.sm5[0, 0])


def test_incomplete_horizon_and_missing_prices_are_invalid_not_labelled() -> None:
    p = flat()
    p["h"][6, 0] = np.nan  # a halted session inside the window
    r = lab(p)
    assert not r.valid[0, 0]
    assert (
        not r.valid[DAYS - 1, 0] and not r.valid[DAYS - 10, 0]
    )  # the last rows have no full window
    assert (
        not r.target_a[0, 0] and r.outcome[0, 0] == NO_EVENT
    )  # invalid rows carry neutral values: callers must use `valid`
    assert lab(flat()).valid[1, 0]


def test_label_at_t_ignores_data_before_the_entry_and_after_the_window() -> None:
    p = flat()
    p["h"][3, 0] = 111.0
    base = lab(p)
    q = {k: v.copy() for k, v in p.items()}
    q["o"][0, 0], q["h"][0, 0], q["l"][0, 0] = (
        50.0,
        300.0,
        1.0,
    )  # the signal bar's own range is not used by the barriers
    q["h"][11:, 0], q["l"][11:, 0], q["c"][11:, 0] = 500.0, 1.0, 7.0  # after the exit
    after = lab(q)
    assert after.outcome[0, 0] == base.outcome[0, 0]
    assert np.isclose(after.exit_return[0, 0], base.exit_return[0, 0])
    assert after.mfe[0, 0] == base.mfe[0, 0]


def test_deterministic_and_stocks_are_independent() -> None:
    rng = np.random.default_rng(3)
    c = 100 * np.cumprod(1 + rng.normal(0, 0.02, (40, 3)), axis=0)
    o, h, lo = c * 0.998, c * 1.01, c * 0.99
    a, b = winner_labels(o, h, lo, c), winner_labels(o, h, lo, c)
    for name in a.__dataclass_fields__:
        assert np.array_equal(getattr(a, name), getattr(b, name), equal_nan=True), name
    one = winner_labels(o[:, :1], h[:, :1], lo[:, :1], c[:, :1])
    assert np.array_equal(one.outcome[:, 0], a.outcome[:, 0])


@settings(max_examples=60, deadline=None)
@given(st.integers(min_value=0, max_value=2**31 - 1))
def test_outcome_agrees_with_the_window_extremes(seed: int) -> None:
    rng = np.random.default_rng(seed)
    n = 30
    c = 100 * np.cumprod(1 + rng.normal(0, 0.03, (n, 1)), axis=0)
    o = np.vstack([c[:1], c[:-1]]) * (1 + rng.normal(0, 0.01, (n, 1)))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.01, (n, 1))))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.01, (n, 1))))
    r = winner_labels(o, h, lo, c)
    for t in range(n - 10):
        entry = o[t + 1, 0]
        hi_w, lo_w = h[t + 1 : t + 11, 0].max(), lo[t + 1 : t + 11, 0].min()
        out = r.outcome[t, 0]
        if out == NO_EVENT:
            assert hi_w < entry * 1.10 and lo_w > entry * 0.95
        if out == SUCCESS:
            assert hi_w >= entry * 1.10 or o[t + 2 : t + 11, 0].max() >= entry * 1.10
        if out == FAILURE:
            assert lo_w <= entry * 0.95
        assert np.isclose(r.mfe[t, 0], hi_w / entry - 1) and np.isclose(
            r.mae[t, 0], lo_w / entry - 1
        )
