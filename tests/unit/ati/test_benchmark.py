"""ATI P2 benchmarks: same-day group means, deciles known at t only."""

from typing import Any

import numpy as np

from algo.ati.benchmark import group_excess, vol_deciles

Arr = np.ndarray[Any, Any]


def test_vol_deciles_rank_within_the_day_and_ignore_nan() -> None:
    third = np.full(20, np.nan)
    third[1:10] = np.arange(9)
    vol = np.array([np.arange(20, dtype=float), np.full(20, np.nan), third])
    d = vol_deciles(vol)
    assert d[0].tolist() == [i // 2 for i in range(20)]
    assert (d[1] == -1).all() and d[2, 0] == -1 and d[2, 1] == 0 and d[2, 9] == 8


def test_group_excess_subtracts_the_same_day_group_mean() -> None:
    fwd = np.array([[0.10, 0.20, 0.30, 0.50], [0.0, 0.0, 0.0, np.nan]])
    g = np.array([[0, 0, 1, 1], [0, 1, -1, 0]])
    ex = group_excess(fwd, g, 2)
    assert np.allclose(ex[0], [-0.05, 0.05, -0.10, 0.10])
    assert np.allclose(ex[1, :2], [0.0, 0.0]) and np.isnan(ex[1, 2]) and np.isnan(ex[1, 3])


def test_future_rows_never_change_earlier_excess() -> None:
    rng = np.random.default_rng(0)
    fwd, vol = rng.normal(size=(30, 12)), rng.uniform(size=(30, 12))
    a = group_excess(fwd, vol_deciles(vol), 10)
    fwd2, vol2 = fwd.copy(), vol.copy()
    fwd2[20:], vol2[20:] = 9.0, 9.0 * rng.uniform(size=(10, 12))
    b = group_excess(fwd2, vol_deciles(vol2), 10)
    assert np.allclose(a[:20], b[:20], equal_nan=True)
