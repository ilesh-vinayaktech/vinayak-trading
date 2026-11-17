# ruff: noqa: E501
"""Sector rotation from index closes: returns over several windows, relative strength against a benchmark, a rotation quadrant, and a score ranked across sectors.
Pure functions, point in time: cutting later days off must not change an earlier day's row."""

import pytest

from algo.market.sectors import quadrant, rotation

N = 320


def path(drift_flat=0.0, drift_late=None, n=N, late=80, start=100.0):
    """A deterministic series: `drift_flat` a day, then `drift_late` a day for the last `late` days."""
    drift_late = (
        drift_flat if drift_late is None else drift_late
    )  # steady unless a different late drift is given
    x, out = start, []
    for i in range(n):
        x *= 1 + (drift_late if i >= n - late else drift_flat)
        out.append(x)
    return out


def test_a_sector_that_keeps_beating_the_benchmark_is_leading_and_one_that_keeps_losing_is_lagging():
    bench = path(0.0005)
    rows = {
        r.name: r
        for r in rotation({"UP": path(0.0015), "DOWN": path(-0.0005), "SAME": path(0.0005)}, bench)
    }
    assert rows["UP"].quadrant == "Leading" and rows["DOWN"].quadrant == "Lagging"
    assert rows["UP"].rs_ratio > 100 > rows["DOWN"].rs_ratio
    assert rows["UP"].score > rows["SAME"].score > rows["DOWN"].score
    assert rows["SAME"].rs_ratio == pytest.approx(100.0, abs=0.01)


def test_a_laggard_that_has_just_turned_up_is_improving_and_a_leader_that_stalled_is_weakening():
    bench = path(0.0005)
    improving = path(
        -0.0015, 0.0030, late=5
    )  # sliding for months, bouncing for the last five days: still behind its norm, but turning
    weakening = path(0.002, -0.0005, late=15)  # far ahead, rolling over in the last 15 days
    rows = {r.name: r for r in rotation({"I": improving, "W": weakening}, bench)}
    assert rows["I"].quadrant == "Improving" and rows["I"].rs_ratio < 100 < rows["I"].rs_momentum
    assert rows["W"].quadrant == "Weakening" and rows["W"].rs_ratio > 100 > rows["W"].rs_momentum


def test_returns_are_over_the_stated_windows_and_trend_flags_use_the_averages():
    bench = path(0.0005)
    s = [100 * 1.001**i for i in range(N)]
    (row,) = rotation({"S": s}, bench)
    assert row.ret_1d == pytest.approx(s[-1] / s[-2] - 1)
    assert row.ret_5d == pytest.approx(s[-1] / s[-6] - 1)
    assert row.ret_21d == pytest.approx(s[-1] / s[-22] - 1)
    assert row.ret_63d == pytest.approx(s[-1] / s[-64] - 1)
    assert row.ret_252d == pytest.approx(s[-1] / s[-253] - 1)
    assert row.above_50 and row.above_200  # a steady riser is above both averages


def test_the_row_for_a_day_does_not_change_when_later_days_are_cut_off():
    bench = path(0.0005)
    series = {"UP": path(0.0015), "DOWN": path(-0.0005)}
    for k in (150, 250, 300):
        full = {r.name: r for r in rotation(series, bench, at=k)}
        cut = {
            r.name: r for r in rotation({n: s[: k + 1] for n, s in series.items()}, bench[: k + 1])
        }
        assert full == cut, k


def test_too_little_history_gives_no_row_and_a_short_sector_is_left_out_not_guessed():
    bench = path(0.0005)
    assert rotation({"A": path(0.001)}, bench[:100]) == []  # not enough for a 200-day average
    rows = rotation({"OK": path(0.001), "SHORT": []}, bench)
    assert [r.name for r in rows] == ["OK"]


@pytest.mark.parametrize(
    ("ratio", "mom", "expected"),
    [
        (101, 101, "Leading"),
        (101, 99, "Weakening"),
        (99, 99, "Lagging"),
        (99, 101, "Improving"),
        (100, 100, "Lagging"),
    ],
)
def test_quadrant_boundaries(ratio, mom, expected):
    assert quadrant(ratio, mom) == expected
