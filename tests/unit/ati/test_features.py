"""ATI P1 feature library: documented, deterministic, versioned, and free of look-ahead (spec 15.2 Test A)."""

from typing import Any

import numpy as np

from algo.ati.features import (
    FEATURE_VERSION,
    GROUPS,
    META,
    ST_MULTS,
    ST_PERIODS,
    compute_features,
    supertrend,
)

Arr = np.ndarray[Any, Any]


def panel(t: int = 420, s: int = 4, seed: int = 3) -> dict[str, Arr]:
    rng = np.random.default_rng(seed)
    c = 100 * np.cumprod(1 + rng.normal(0.0004, 0.02, (t, s)), axis=0)
    o = c * (1 + rng.normal(0, 0.004, (t, s)))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.006, (t, s))))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.006, (t, s))))
    v = rng.integers(10_000, 100_000, (t, s)).astype(float)
    return {"o": o, "h": h, "lo": lo, "c": c, "v": v}


def feats(p: dict[str, Arr]) -> dict[str, Arr]:
    return {m.name: a for m, a in compute_features(p["o"], p["h"], p["lo"], p["c"], p["v"])}


def test_version_groups_and_documentation() -> None:
    f = feats(panel())
    assert FEATURE_VERSION == "ati-f1"
    assert set(f) == set(META)
    assert {m.group for m in META.values()} == set(GROUPS)
    assert len([n for n in META if n.startswith("st_")]) == 4 * len(ST_PERIODS) * len(ST_MULTS)
    for m in META.values():
        assert m.description and m.lookback >= 1
    for a in f.values():
        assert a.shape == (420, 4) and a.dtype == np.float32


def test_group_filter_and_determinism() -> None:
    p = panel()
    g = [
        m.name for m, _ in compute_features(p["o"], p["h"], p["lo"], p["c"], p["v"], ("momentum",))
    ]
    assert g and all(META[n].group == "momentum" for n in g)
    a, b = feats(p), feats(p)
    assert all(np.array_equal(a[k], b[k], equal_nan=True) for k in a)


def test_future_candle_mutation_leaves_history_unchanged() -> None:
    """Test A: change every OHLCV value after row cut; every feature row <= cut must be identical."""
    p = panel()
    cut = 300
    q = {k: a.copy() for k, a in p.items()}
    rng = np.random.default_rng(9)
    for k in q:
        q[k][cut + 1 :] *= rng.uniform(0.5, 2.0, q[k][cut + 1 :].shape)
    a, b = feats(p), feats(q)
    for k in a:
        assert np.array_equal(a[k][: cut + 1], b[k][: cut + 1], equal_nan=True), k


def test_warmup_is_nan_and_values_after_it_exist() -> None:
    f = feats(panel())
    for name, meta in META.items():
        assert np.isnan(f[name][: meta.lookback - 1]).all(), name
    assert (
        np.isfinite(f["ema_200_distance"][-1]).all()
        and np.isfinite(f["st_10_3_0_direction"][-1]).all()
    )


def test_known_values() -> None:
    p = panel()
    f = feats(p)
    c = p["c"]
    assert np.allclose(f["momentum_5"][10], (c[10] - c[5]) / c[10], rtol=1e-5)
    assert np.allclose(f["roc_10"][20], c[20] / c[10] - 1, rtol=1e-5)
    assert np.all((f["rsi_14"][50:] >= 0) & (f["rsi_14"][50:] <= 100))
    assert np.all((f["stoch_k_14"][20:] >= 0) & (f["stoch_k_14"][20:] <= 100))
    assert np.all(f["distance_to_20d_high"][25:] <= 1e-6)
    assert np.all(f["ema_bullish_alignment"][250:] + f["ema_bearish_alignment"][250:] <= 1)
    assert np.allclose(f["relative_volume"][30], p["v"][30] / p["v"][11:31].mean(0), rtol=1e-5)


def test_supertrend_flips_on_trend_reversal() -> None:
    t = 120
    c = np.concatenate([np.linspace(100, 200, 60), np.linspace(200, 100, 60)])[:, None]
    h, lo = c + 1, c - 1
    atr = np.full((t, 1), 2.0)
    d, line = supertrend(h, lo, c, atr, 2.0)
    assert d[30, 0] == 1 and line[30, 0] < c[30, 0]
    assert d[-1, 0] == -1 and line[-1, 0] > c[-1, 0]
    assert np.isnan(supertrend(h, lo, c, np.full((t, 1), np.nan), 2.0)[0]).all()


def test_supertrend_flip_and_age_features() -> None:
    f = feats(panel())
    d, flip, age = f["st_10_3_0_direction"], f["st_10_3_0_flip"], f["st_10_3_0_signal_age"]
    ok = np.isfinite(d[1:]) & np.isfinite(d[:-1])
    assert np.array_equal(flip[1:][ok] == 1, (d[1:] != d[:-1])[ok])
    assert np.all(age[flip == 1] == 0) and np.nanmax(age) <= 60
