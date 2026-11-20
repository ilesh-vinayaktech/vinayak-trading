"""ATI P2 regimes: each rule fires on its own inputs, history never changes when the future does (spec 15.2 Test D), clustering is fitted on training rows only."""

from typing import Any

import numpy as np

from algo.ati.features import compute_features
from algo.ati.regime import (
    CLUSTER_FEATURES,
    CODE,
    NEEDED,
    REGIMES,
    UNKNOWN,
    assign_clusters,
    breadth,
    cluster_matrix,
    fit_clusters,
    market_index,
    rule_regimes,
)

Arr = np.ndarray[Any, Any]
NEUTRAL = {
    "vol_expansion": 1.0, "vol_contraction": 1.0, "ema_50_slope": 0.0, "ema_20_distance": 0.0,
    "ema_50_distance": 0.0, "momentum_10": 0.0, "rsi_14": 50.0, "ema_bullish_alignment": 0.0,
}  # fmt: skip


def one(**kw: float) -> str:
    f = {k: np.array([kw.get(k, v)]) for k, v in NEUTRAL.items()}
    code = int(rule_regimes(f)[0])
    return "UNKNOWN" if code == UNKNOWN else REGIMES[code]


def panel(t: int = 420, s: int = 5, seed: int = 3) -> dict[str, Arr]:
    rng = np.random.default_rng(seed)
    c = 100 * np.cumprod(1 + rng.normal(0.0004, 0.02, (t, s)), axis=0)
    o = c * (1 + rng.normal(0, 0.004, (t, s)))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.006, (t, s))))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.006, (t, s))))
    v = rng.integers(10_000, 100_000, (t, s)).astype(float)
    return {"o": o, "h": h, "lo": lo, "c": c, "v": v}


def feats(p: dict[str, Arr]) -> dict[str, Arr]:
    return {
        m.name: a
        for m, a in compute_features(
            p["o"],
            p["h"],
            p["lo"],
            p["c"],
            p["v"],
            ("trend", "momentum", "volatility", "volume", "channel"),
        )
    }


def test_each_rule_fires_on_its_inputs_and_in_priority_order() -> None:
    assert one() == "SIDEWAYS"
    assert one(vol_expansion=1.6) == "VOLATILITY_EXPANSION"
    assert (
        one(vol_expansion=1.6, ema_50_slope=0.01, ema_20_distance=-1, momentum_10=-1)
        == "VOLATILITY_EXPANSION"
    )
    assert one(ema_50_slope=-0.01, ema_20_distance=0.02, momentum_10=0.03) == "POTENTIAL_REVERSAL"
    assert one(ema_50_slope=0.01, ema_20_distance=-0.02, momentum_10=-0.03) == "POTENTIAL_REVERSAL"
    assert (
        one(
            ema_50_slope=0.01,
            ema_50_distance=0.05,
            ema_20_distance=0.03,
            rsi_14=60,
            ema_bullish_alignment=1,
        )
        == "STRONG_UPTREND"
    )
    assert (
        one(
            ema_50_slope=0.01,
            ema_50_distance=0.05,
            ema_20_distance=0.03,
            rsi_14=50,
            ema_bullish_alignment=1,
        )
        == "WEAK_UPTREND"
    )
    assert one(ema_50_slope=-0.01, ema_50_distance=-0.05, ema_20_distance=-0.03) == "DOWNTREND"
    assert one(vol_contraction=0.5) == "VOLATILITY_CONTRACTION"
    assert one(vol_contraction=0.6) == "SIDEWAYS"


def test_any_nan_input_is_unknown() -> None:
    for k in NEEDED:
        assert one(**{k: np.nan}) == "UNKNOWN", k


def test_history_does_not_change_when_the_future_does() -> None:
    """Test D: features and regimes of every row <= cut are identical after all later OHLCV is mutated."""
    p, cut = panel(), 330
    q = {k: a.copy() for k, a in p.items()}
    rng = np.random.default_rng(9)
    for k in q:
        q[k][cut + 1 :] *= rng.uniform(0.5, 2.0, q[k][cut + 1 :].shape)
    a, b = rule_regimes(feats(p)), rule_regimes(feats(q))
    assert np.array_equal(a[: cut + 1], b[: cut + 1])
    assert np.array_equal(market_index(p["c"])[: cut + 1], market_index(q["c"])[: cut + 1])
    assert (a[cut] != UNKNOWN).any() and len(set(a[a != UNKNOWN].ravel().tolist())) >= 4


def test_market_index_and_breadth() -> None:
    c = np.array([[100.0, 100.0], [110.0, 100.0], [110.0, np.nan]])
    assert np.allclose(market_index(c), [100, 105, 105])
    assert market_index(np.full((3, 1), np.nan)).tolist() == [100, 100, 100]
    d = np.array([[0.1, -0.1, np.nan], [np.nan, np.nan, np.nan]])
    b = breadth(d)
    assert b[0] == 0.5 and np.isnan(b[1])


def test_clusters_use_training_rows_only() -> None:
    p, cut = panel(t=500), 400
    f, c = feats(p), p["c"]
    x = cluster_matrix(f, c)
    assert x.shape == (500 * 5, len(CLUSTER_FEATURES))
    rows = np.arange(len(x)).reshape(500, 5)
    train = x[rows[:cut].ravel()]
    m1 = fit_clusters(train, 3, seed=1)
    q = {k: a.copy() for k, a in p.items()}
    for k in q:
        q[k][cut:] *= 3.0
    x2 = cluster_matrix(feats(q), q["c"])
    m2 = fit_clusters(x2[rows[:cut].ravel()], 3, seed=1)
    assert np.allclose(m1.km.cluster_centers_, m2.km.cluster_centers_) and np.allclose(
        m1.mean, m2.mean
    )
    lab = assign_clusters(m1, x)
    assert (
        set(lab[np.isfinite(x).all(1)].tolist()) <= {0, 1, 2}
        and (lab[~np.isfinite(x).all(1)] == -1).all()
    )
    assert (assign_clusters(m1, np.full((2, 8), np.nan)) == -1).all()


def test_fit_subsamples_large_training_sets_deterministically() -> None:
    rng = np.random.default_rng(0)
    x = rng.normal(size=(500, 8))
    x[:, 0] = 1.0  # constant column: std 0 must not divide by zero
    a, b = fit_clusters(x, 2, seed=4, max_rows=200), fit_clusters(x, 2, seed=4, max_rows=200)
    assert np.allclose(a.km.cluster_centers_, b.km.cluster_centers_) and a.std[0] == 1.0
    assert CODE["SIDEWAYS"] == REGIMES.index("SIDEWAYS")


def test_gmm_option_is_train_only_and_unknown_method_is_rejected() -> None:
    import pytest

    rng = np.random.default_rng(1)
    x = np.vstack([rng.normal(0, 1, (300, 8)), rng.normal(6, 1, (300, 8))])
    m = fit_clusters(x, 2, seed=0, method="gmm")
    lab = assign_clusters(m, x)
    assert (
        len(set(lab[:300].tolist())) == 1
        and len(set(lab[300:].tolist())) == 1
        and lab[0] != lab[-1]
    )
    with pytest.raises(ValueError):
        fit_clusters(x, 2, method="nope")
