"""Swing features: each is known at the day's close (truncating later data changes nothing)."""

import numpy as np

from algo.research import swing_features as sf


def _panel(t=120, s=3, seed=1):
    r = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(r.normal(0, 0.01, (t, s)), axis=0))
    o = c * (1 + r.normal(0, 0.002, (t, s)))
    h = np.maximum(o, c) * (1 + np.abs(r.normal(0, 0.003, (t, s))))
    lo = np.minimum(o, c) * (1 - np.abs(r.normal(0, 0.003, (t, s))))
    v = r.uniform(1e5, 2e5, (t, s))
    dq = v * r.uniform(0.3, 0.6, (t, s))
    return o, h, lo, c, v, dq


def test_no_lookahead_truncation():
    p = _panel()
    full = sf.features(*p)
    cut = sf.features(*(x[:90] for x in p))
    assert set(full) == set(cut) == set(sf.META)
    for k in full:
        np.testing.assert_allclose(full[k][:90], cut[k], equal_nan=True, err_msg=k)


def test_deterministic():
    p = _panel()
    a, b = sf.features(*p), sf.features(*p)
    assert all(np.array_equal(a[k], b[k], equal_nan=True) for k in a)


def test_hand_worked_values():
    t = 60
    c = np.linspace(100, 159, t)[:, None]
    o, h, lo = c - 0.5, c + 1.0, c - 1.0
    v = np.full((t, 1), 1000.0)
    dq = np.full((t, 1), 400.0)
    f = sf.features(o, h, lo, c, v, dq)
    assert np.isclose(f["ret_1"][30, 0], c[30, 0] / c[29, 0] - 1)
    assert np.isclose(f["ret_5"][30, 0], c[30, 0] / c[25, 0] - 1)
    assert np.isclose(f["close_loc"][30, 0], 0.5)  # (c-lo)/(h-lo) = 1/2
    assert np.isclose(f["gap"][30, 0], o[30, 0] / c[29, 0] - 1)
    assert np.isclose(f["rel_vol"][30, 0], 1.0)
    assert np.isclose(f["deliv_pct"][30, 0], 0.4)
    assert np.isclose(f["up_streak"][30, 0], 30)
    assert f["rsi_14"][59, 0] == 100.0  # only up days
