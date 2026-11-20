"""ATR triple-barrier labels: hand-worked outcomes, gap and ambiguity rules, no look-ahead."""

import numpy as np

from algo.research import swing_labels as sl

NAN = np.nan


def _bars(rows):
    """rows: (open, high, low, close) per session -> four (T,1) arrays."""
    a = np.array(rows, dtype=float)
    return tuple(a[:, i : i + 1] for i in range(4))


def _label(rows, atr=2.0, **kw):
    o, h, lo, c = _bars(rows)
    at = np.full_like(c, atr)
    return sl.barrier_labels(o, h, lo, c, at, up=1.5, dn=1.0, horizon=kw.pop("horizon", 4), **kw)


FLAT = (100, 100.5, 99.5, 100)


def test_profit_first_uses_the_barrier_price():
    # signal day 0, entry at open of day 1 = 100, atr 2 -> upper 103, lower 98
    r = _label([FLAT, (100, 101, 99.5, 100.5), (100.5, 103.5, 100, 103), FLAT, FLAT, FLAT])
    assert r.outcome[0, 0] == sl.PROFIT_FIRST
    assert np.isclose(r.ret[0, 0], 0.03)
    assert r.sessions[0, 0] == 2
    assert np.isclose(r.mfe[0, 0], 0.035) and np.isclose(r.mae[0, 0], -0.005)


def test_loss_first_and_entry_day_counts():
    r = _label([FLAT, (100, 100.5, 97.5, 98), FLAT, FLAT, FLAT, FLAT])
    assert r.outcome[0, 0] == sl.LOSS_FIRST and np.isclose(r.ret[0, 0], -0.02)
    assert r.sessions[0, 0] == 1


def test_both_barriers_in_one_bar_is_a_flagged_loss():
    r = _label([FLAT, (100, 104, 97, 100), FLAT, FLAT, FLAT, FLAT])
    assert r.outcome[0, 0] == sl.LOSS_FIRST and r.ambiguous[0, 0]
    assert np.isclose(r.ret[0, 0], -0.02)


def test_gap_through_stop_exits_at_the_open_not_the_stop():
    r = _label([FLAT, (100, 100.5, 99.5, 100), (95, 96, 94, 95), FLAT, FLAT, FLAT])
    assert r.outcome[0, 0] == sl.LOSS_FIRST and np.isclose(r.ret[0, 0], -0.05)
    assert not r.ambiguous[0, 0]


def test_gap_up_through_target_exits_at_the_open():
    r = _label([FLAT, (100, 100.5, 99.5, 100), (106, 107, 105, 106), FLAT, FLAT, FLAT])
    assert r.outcome[0, 0] == sl.PROFIT_FIRST and np.isclose(r.ret[0, 0], 0.06)


def test_timeout_keeps_return_and_excursions():
    q = (100, 101, 99.5, 100.5)
    r = _label([FLAT, q, q, q, (100, 101, 99, 101), FLAT])
    assert r.outcome[0, 0] == sl.TIMEOUT and np.isclose(r.ret[0, 0], 0.01)
    assert r.sessions[0, 0] == 4 and np.isclose(r.mae[0, 0], -0.01)


def test_unlabelled_without_a_full_window_or_atr():
    r = _label([FLAT, FLAT, FLAT])
    assert (r.outcome == sl.NONE).all()
    o, h, lo, c = _bars([FLAT] * 6)
    at = np.full_like(c, NAN)
    assert (sl.barrier_labels(o, h, lo, c, at, 1.5, 1.0, 4).outcome == sl.NONE).all()


def test_no_lookahead_beyond_the_window():
    rows = [FLAT, (100, 101, 99.5, 100.5), (100.5, 101, 100, 100.8), FLAT, FLAT, FLAT, FLAT]
    a = _label(rows)
    rows2 = rows[:6] + [(1, 1000, 0.1, 500)]  # wreck the session after the window
    b = _label(rows2)
    assert a.outcome[0, 0] == b.outcome[0, 0] and a.ret[0, 0] == b.ret[0, 0]


def test_atr_is_the_simple_mean_of_true_range():
    o, h, lo, c = _bars([(10, 12, 9, 11), (11, 13, 10, 12), (12, 14, 11, 13)])
    a = sl.atr(h, lo, c, 2)
    assert np.isnan(a[0, 0])
    assert np.isclose(a[2, 0], 3.0)  # every true range is 3
