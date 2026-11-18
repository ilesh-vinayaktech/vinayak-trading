# ruff: noqa: E501
"""The per-stock notes on bars with known answers: each rule fires on the case it names, stays quiet otherwise, and the result is ordered by importance."""

import numpy as np

from algo.market import notes
from algo.market.notes import LiveDay, Note, price_notes, rsi


def ranging(n=160, lo=100.0, hi=110.0, period=20):
    """A stock bouncing between 100 and 110: support and resistance pile up at the edges (the same fixture as the levels tests)."""
    t = np.arange(n)
    mid = (lo + hi) / 2 + (hi - lo) / 2 * np.sin(2 * np.pi * t / period)
    return list(mid + 0.3), list(mid - 0.3), list(mid), [1000.0] * n


def kinds(ns):
    return [x.kind for x in ns]


def bars_with(close_today, volume_today, n=160):
    high, low, close, vol = ranging(n)
    (
        high.append(close_today + 0.3),
        low.append(108.0),
        close.append(close_today),
        vol.append(volume_today),
    )
    return high, low, close, vol, [None] * len(close)


def test_a_close_through_resistance_on_heavy_volume_is_a_breakout_and_on_light_volume_a_weak_one():
    assert "breakout" in kinds(price_notes(*bars_with(113.0, 2500.0)))
    weak = price_notes(*bars_with(113.0, 1000.0))
    assert "breakout_weak" in kinds(weak) and "breakout" not in kinds(weak)


def test_a_close_through_support_is_a_breakdown():
    high, low, close, vol = ranging(160)
    high.append(97.3), low.append(96.8), close.append(97.0), vol.append(3000.0)
    got = price_notes(high, low, close, vol, [None] * 161)
    assert got[0].kind == "breakdown" and got[0].tone == "bad" and got[0].rank == notes.RANK_BREAK


def test_just_under_resistance_is_near_breakout_and_a_live_price_through_it_is_a_breakout_today():
    high, low, close, vol = ranging(160)
    delivery = [None] * 160
    res = max(h for h in high[-40:])
    near = price_notes(
        high, low, close, vol, delivery, LiveDay(None, res, res - 2, res * 0.996, 500.0)
    )
    assert (
        "near_breakout" in kinds(near)
        or "breakout" in kinds(near)
        or "breakout_weak" in kinds(near)
    )
    through = price_notes(
        high, low, close, vol, delivery, LiveDay(None, 114.0, 108.0, 113.0, 5000.0)
    )
    assert {"breakout", "breakout_weak"} & set(
        kinds(through)
    )  # seen today, with the volume that has traded so far


def test_an_inside_bar_and_the_narrowest_range_in_a_week_are_coiling_notes():
    high, low, close, vol = ranging(160)
    high[-1], low[-1] = (
        high[-2] - 0.1,
        low[-2] + 0.1,
    )  # inside the day before, and narrower than the last six
    got = kinds(price_notes(high, low, close, vol, [None] * 160))
    assert "inside_bar" in got and "nr7" in got
    high, low, close, vol = ranging(160)
    assert "inside_bar" not in kinds(price_notes(high, low, close, vol, [None] * 160))


def test_a_volume_surge_is_good_on_an_up_day_and_bad_on_a_down_day_and_a_delivery_surge_needs_a_norm():
    high, low, close, vol = ranging(160)
    vol[-1] = 5000.0
    close[-1], close[-2] = close[-2] + 1, close[-2]
    up = price_notes(high, low, close, vol, [None] * 160)
    assert next(x for x in up if x.kind == "volume_surge").tone == "good"
    close[-1] = close[-2] - 1
    assert (
        next(
            x for x in price_notes(high, low, close, vol, [None] * 160) if x.kind == "volume_surge"
        ).tone
        == "bad"
    )
    deliv = [40.0] * 159 + [70.0]
    assert "delivery_surge" in kinds(price_notes(high, low, close, vol, deliv))
    assert "delivery_surge" not in kinds(
        price_notes(high, low, close, vol, [None] * 159 + [70.0])
    )  # no earlier days to compare with


def test_a_gap_and_a_big_move_come_from_the_live_day_only():
    high, low, close, vol = ranging(160)
    prev = close[-1]
    up = price_notes(
        high,
        low,
        close,
        vol,
        [None] * 160,
        LiveDay(prev * 1.03, prev * 1.06, prev * 1.02, prev * 1.05, 900.0),
    )
    assert {"gap_up", "big_up"} <= set(kinds(up))
    down = price_notes(
        high,
        low,
        close,
        vol,
        [None] * 160,
        LiveDay(prev * 0.97, prev * 0.98, prev * 0.93, prev * 0.94, 900.0),
    )
    assert {"gap_down", "big_down"} <= set(kinds(down))
    calm = price_notes(
        high,
        low,
        close,
        vol,
        [None] * 160,
        LiveDay(prev, prev * 1.001, prev * 0.999, prev * 1.001, 900.0),
    )
    assert not {"gap_up", "gap_down", "big_up", "big_down"} & set(kinds(calm))
    assert not {"gap_up", "gap_down", "big_up", "big_down"} & set(
        kinds(price_notes(high, low, close, vol, [None] * 160))
    )  # no live day: no intraday notes


def test_a_new_52_week_high_or_low_and_being_near_one():
    close = list(np.linspace(50, 150, 260))
    high, low = [c + 0.5 for c in close], [c - 0.5 for c in close]
    vol = [1000.0] * 260
    got = kinds(
        price_notes(high, low, close, vol, [None] * 260, LiveDay(None, 152, 150, 151, 100.0))
    )
    assert "new_high" in got and "new_low" not in got
    near = kinds(
        price_notes(high, low, close, vol, [None] * 260, LiveDay(None, 150.4, 149, 149.5, 100.0))
    )
    assert "near_high" in near and "new_high" not in near
    falling = list(np.linspace(150, 50, 260))
    h2, l2 = [c + 0.5 for c in falling], [c - 0.5 for c in falling]
    low_now = kinds(
        price_notes(h2, l2, falling, vol, [None] * 260, LiveDay(None, 50, 48, 49, 100.0))
    )
    assert "new_low" in low_now and "below_200" in low_now
    assert "new_high" not in kinds(
        price_notes(*ranging(100)[:3], vol[:100], [None] * 100)
    )  # under 200 bars: extremes mean nothing yet


def test_rsi_is_100_for_a_straight_rise_and_0_for_a_straight_fall_and_flags_overbought_and_oversold():
    assert (
        rsi(list(range(1, 40))) == 100.0
        and rsi(list(range(40, 1, -1))) == 0.0
        and rsi([5.0] * 30) == 50.0
    )
    assert rsi([1.0] * 10) is None
    up = list(np.linspace(50, 80, 60))
    h, l_, v = [c + 0.5 for c in up], [c - 0.5 for c in up], [1000.0] * 60
    assert "overbought" in kinds(price_notes(h, l_, up, v, [None] * 60))
    down = list(np.linspace(80, 50, 60))
    h, l_ = [c + 0.5 for c in down], [c - 0.5 for c in down]
    assert "oversold" in kinds(price_notes(h, l_, down, v, [None] * 60))


def cut(close, end):
    return (
        [c + 1 for c in close[: end + 1]],
        [c - 1 for c in close[: end + 1]],
        close[: end + 1],
        [1000.0] * (end + 1),
        [None] * (end + 1),
    )


def test_a_fresh_golden_cross_is_noted_for_five_sessions_then_it_is_old_news():
    close = (
        [100.0] * 230 + [100.0 + 2 * k for k in range(1, 61)]
    )  # flat, then rising: the 50-day average crosses the 200-day on the first rising day (index 230)
    assert "golden_cross" in kinds(price_notes(*cut(close, 232)))
    assert "golden_cross" not in kinds(price_notes(*cut(close, 238)))  # eight sessions on
    assert "golden_cross" not in kinds(price_notes(*cut(close, 229)))  # before it happened


def test_a_fresh_death_cross_is_bad():
    close = [100.0] * 230 + [100.0 - 1.5 * k for k in range(1, 61)]
    got = [
        x
        for end in range(230, 236)
        for x in price_notes(*cut(close, end))
        if x.kind == "death_cross"
    ]
    assert got and all(x.tone == "bad" for x in got)
    assert "death_cross" not in kinds(price_notes(*cut(close, 240)))


def test_too_little_or_ragged_data_gives_no_notes_and_the_result_is_ordered_and_repeatable():
    assert price_notes([1.0], [1.0], [1.0], [1.0], [None]) == []
    assert price_notes([1.0, 2.0], [1.0, 2.0], [1.0, 2.0], [1.0], [None, None]) == []
    args = bars_with(113.0, 2500.0)
    a = price_notes(*args, LiveDay(None, 114.0, 108.0, 113.0, 5000.0))
    assert a == price_notes(*args, LiveDay(None, 114.0, 108.0, 113.0, 5000.0))
    assert [x.rank for x in a] == sorted(x.rank for x in a) and all(isinstance(x, Note) for x in a)


def test_a_stock_that_has_not_moved_all_year_has_no_52_week_extremes():
    flat = [100.0] * 260
    got = kinds(
        price_notes(
            [100.5] * 260,
            [99.5] * 260,
            flat,
            [1000.0] * 260,
            [None] * 260,
            LiveDay(None, 100.5, 99.5, 100.0, 10.0),
        )
    )
    assert not {"new_high", "near_high", "new_low", "near_low"} & set(got)
