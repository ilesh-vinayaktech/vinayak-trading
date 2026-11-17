# ruff: noqa: E501
"""Support and resistance from swing pivots, volume at price, the return histogram and breakout status, on bars with known answers."""

import numpy as np
import pytest

from algo.market import levels


def ranging(n=160, lo=100.0, hi=110.0, period=20):
    """A stock bouncing between 100 and 110: pivots pile up at both edges."""
    t = np.arange(n)
    mid = (lo + hi) / 2 + (hi - lo) / 2 * np.sin(2 * np.pi * t / period)
    return mid + 0.3, mid - 0.3, mid, np.full(n, 1000.0)  # high, low, close, volume


def test_a_ranging_stock_has_support_and_resistance_at_the_edges_with_several_touches():
    high, low, close, vol = ranging()
    out = levels.analyse(high, low, close, vol)
    sup, res = out["supports"], out["resistances"]
    assert sup[0]["price"] == pytest.approx(99.7, abs=0.6) or res[0]["price"] == pytest.approx(
        110.3, abs=0.6
    )
    top = max(res + sup, key=lambda x: x["touches"])
    assert top["touches"] >= 3
    assert all(s["price"] < out["price"] for s in sup) and all(
        r["price"] > out["price"] for r in res
    )
    assert all(s["distance_pct"] < 0 for s in sup) and all(r["distance_pct"] > 0 for r in res)


def test_a_pivot_is_known_only_k_bars_after_it_so_the_last_bars_never_make_one():
    high = [10.0] * 30 + [20.0] + [10.0] * 3  # a spike with only 3 bars after it
    low = [h - 1 for h in high]
    assert all(i != 30 for i, _ in levels.swing_points(high, low))
    high2 = high + [10.0] * 3
    assert (30, 20.0) in levels.swing_points(high2, [h - 1 for h in high2])


def test_pivots_found_by_day_t_are_exactly_those_the_full_history_finds_before_t_minus_k():
    high, low, close, vol = ranging(200)
    cut = 150
    full = [p for p in levels.swing_points(high, low) if p[0] < cut - levels.PIVOT_K]
    prefix = [p for p in levels.swing_points(high[:cut], low[:cut]) if p[0] < cut - levels.PIVOT_K]
    assert full == prefix  # nothing after the cut can change which earlier bars are pivots
    spiked = np.concatenate([high[:cut], [999.0], high[cut + 1 :]])
    assert levels.analyse(high[:cut], low[:cut], close[:cut], vol[:cut]) == levels.analyse(
        spiked[:cut], low[:cut], close[:cut], vol[:cut]
    )


def breakout_series(volume_today, close_today=113.0):
    high, low, close, vol = (list(x) for x in ranging(160))
    (
        high.append(close_today + 0.3),
        low.append(108.0),
        close.append(close_today),
        vol.append(volume_today),
    )
    return high, low, close, vol


def test_a_close_through_resistance_on_heavy_volume_is_a_confirmed_breakout_and_on_light_volume_a_weak_one():
    assert levels.status(*breakout_series(2500.0))["state"] == "Breakout"
    assert levels.status(*breakout_series(1000.0))["state"] == "Breakout, weak volume"
    assert (
        levels.status(*breakout_series(2500.0), delivery_vs_avg=0.8)["state"]
        == "Breakout, weak volume"
    )  # people did not take delivery
    assert levels.status(*breakout_series(2500.0), delivery_vs_avg=1.5)["state"] == "Breakout"


def test_a_close_through_support_is_a_breakdown_and_one_beside_a_level_is_testing_it():
    high, low, close, vol = (list(x) for x in ranging(160))
    high.append(97.3), low.append(96.8), close.append(97.0), vol.append(3000.0)
    assert levels.status(high, low, close, vol)["state"] == "Breakdown"
    high, low, close, vol = (list(x) for x in ranging(160))
    close[-2] = 106.0
    prior = levels.nearest(
        levels.clusters(levels.swing_points(high[:-1], low[:-1]), len(close) - 2, close[-2]),
        close[-2],
    )
    close[-1] = (
        prior[1][0].price * 0.995
    )  # a hair under the nearest resistance above the previous close
    st = levels.status(high, low, close, vol)
    assert st["state"] == "Testing resistance" and st["level"] is not None


def test_the_volume_profile_puts_the_point_of_control_where_most_volume_traded():
    n = 120
    high, low = np.full(n, 105.0), np.full(n, 95.0)
    high[:100], low[:100] = 101.0, 99.0  # most days squeezed into 99 to 101
    vol = np.full(n, 1000.0)
    p = levels.volume_profile(high, low, vol)
    assert 98.5 <= p["poc"] <= 101.5 and p["value_low"] <= p["poc"] <= p["value_high"]
    assert (
        sum(b["share"] for b in p["bins"]) == pytest.approx(1.0) and len(p["bins"]) == levels.BINS
    )


def test_the_return_histogram_counts_every_day_and_places_the_last_move():
    rng = np.random.default_rng(2)
    close = 100 * np.cumprod(1 + rng.normal(0, 0.01, 300))
    h = levels.return_histogram(close)
    assert (
        sum(b["count"] for b in h["bins"]) == 250
        and 0 <= h["last_percentile"] <= 100
        and h["worst"] < 0 < h["best"]
    )


def test_too_little_or_ragged_history_gives_nothing_rather_than_a_guess():
    high, low, close, vol = ranging(40)
    assert levels.analyse(high, low, close, vol) is None
    high, low, close, vol = ranging(100)
    assert levels.analyse(high[:-1], low, close, vol) is None
    assert levels.volume_profile([1.0] * 5, [1.0] * 5, [1.0] * 5) is None
    assert levels.return_histogram([100.0] * 10) is None
