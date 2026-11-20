# ruff: noqa: E501
"""ATI P2: market-regime detection (spec section 5). Research categories only, not guaranteed market states.
(Not `algo.portfolio.regime`: that is a two-label benchmark classifier for plan.md; this is the spec's seven categories on a stock panel, plus clustering.)

Rule regimes (`rule_regimes`): one code per stock-day from the `ati-f1` features, known at the close of t. The thresholds are FIXED here before any run and never tuned on outcomes.
First rule that holds wins, in this order:
  VOLATILITY_EXPANSION    vol_expansion > 1.5                       (ATR14 more than 1.5x its value 20 sessions ago)
  POTENTIAL_REVERSAL      50-day EMA slope against the 20-day EMA side AND 10-day momentum against that slope
                          (slope < 0, close above EMA20, momentum_10 > 0: a downtrend turning up; slope > 0, close below EMA20, momentum_10 < 0: an uptrend rolling over)
  STRONG_UPTREND          bullish EMA alignment AND ema_50_slope > 0 AND RSI14 > 55
  WEAK_UPTREND            close above EMA50 AND ema_50_slope > 0
  DOWNTREND               close below EMA50 AND ema_50_slope < 0
  VOLATILITY_CONTRACTION  vol_contraction < 0.6                     (ATR14 below 60% of its 60-session maximum)
  SIDEWAYS                everything else
UNKNOWN (-1) while any input is NaN (warm-up, missing bars).
Market regime: `market_index` builds an equal-weight index from the same day's stock returns; feed it through the same features and rules as a one-column panel (open = high = low = close, so ATR-based inputs are close-to-close). `breadth` is the share of stocks above their EMA50.
Clusters (`fit_clusters`/`assign_clusters`): K-Means on the spec's 8 features; the scaler and the centres are fitted on the TRAINING rows passed in and nothing else.
Pure functions of the arrays: no clock, no I/O."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.cluster import KMeans  # type: ignore[import-untyped]
from sklearn.mixture import GaussianMixture  # type: ignore[import-untyped]

Arr = np.ndarray[Any, Any]
REGIME_VERSION = "ati-r1"
REGIMES = (
    "STRONG_UPTREND",
    "WEAK_UPTREND",
    "DOWNTREND",
    "SIDEWAYS",
    "VOLATILITY_EXPANSION",
    "VOLATILITY_CONTRACTION",
    "POTENTIAL_REVERSAL",
)
UNKNOWN = -1
CODE = {n: i for i, n in enumerate(REGIMES)}
NEEDED = (
    "vol_expansion",
    "vol_contraction",
    "ema_50_slope",
    "ema_20_distance",
    "ema_50_distance",
    "momentum_10",
    "rsi_14",
    "ema_bullish_alignment",
)
CLUSTER_FEATURES = (
    "ret_5d_norm",
    "ret_20d_norm",
    "ret_50d_norm",
    "atr_pct_14",
    "vol_percentile_252",
    "ema_20_50_spread",
    "relative_volume",
    "bb_width_20",
)


def rule_regimes(f: dict[str, Arr]) -> Arr:
    """int8 array (same shape as the features) of regime codes from the feature arrays named in NEEDED; UNKNOWN where an input is NaN."""
    exp, con, slope = f["vol_expansion"], f["vol_contraction"], f["ema_50_slope"]
    d20, d50, mom, rsi, bull = (
        f["ema_20_distance"],
        f["ema_50_distance"],
        f["momentum_10"],
        f["rsi_14"],
        f["ema_bullish_alignment"],
    )
    ok = np.isfinite(np.stack([f[k] for k in NEEDED])).all(0)
    with np.errstate(invalid="ignore"):
        rules = [
            (exp > 1.5, "VOLATILITY_EXPANSION"),
            (
                ((slope < 0) & (d20 > 0) & (mom > 0)) | ((slope > 0) & (d20 < 0) & (mom < 0)),
                "POTENTIAL_REVERSAL",
            ),
            ((bull == 1) & (slope > 0) & (rsi > 55), "STRONG_UPTREND"),
            ((d50 > 0) & (slope > 0), "WEAK_UPTREND"),
            ((d50 < 0) & (slope < 0), "DOWNTREND"),
            (con < 0.6, "VOLATILITY_CONTRACTION"),
        ]
    out: Arr = np.full(slope.shape, CODE["SIDEWAYS"], dtype="int8")
    # the first rule wins: apply the last first and let earlier ones overwrite
    for cond, name in reversed(rules):
        out = np.where(cond, CODE[name], out).astype("int8")
    return np.where(ok, out, UNKNOWN).astype("int8")


def market_index(c: Arr) -> Arr:
    """Equal-weight index (start 100) from the same day's stock returns: row t uses closes t and t-1 only."""
    with np.errstate(invalid="ignore", divide="ignore"):
        r = c[1:] / c[:-1] - 1
    good = np.isfinite(r)
    day = np.where(good, r, 0.0).sum(1) / np.maximum(good.sum(1), 1)
    return 100 * np.concatenate([[1.0], np.cumprod(1 + day)])


def breadth(ema_50_distance: Arr) -> Arr:
    """Share of stocks with close above EMA50 on each day (NaN when no stock has the feature)."""
    ok = np.isfinite(ema_50_distance)
    n = ok.sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n > 0, (np.where(ok, ema_50_distance, -1) > 0).sum(1) / n, np.nan)


@dataclass(frozen=True)
class ClusterModel:
    mean: Arr
    std: Arr
    km: Any  # a fitted KMeans or GaussianMixture: both have predict()
    k: int
    seed: int


def cluster_matrix(f: dict[str, Arr], c: Arr) -> Arr:
    """rows x 8 matrix (one row per stock-day, day-major) of the spec's clustering inputs. Normalised return = k-day return / (hist_vol_20 * sqrt(k))."""
    hv = f["hist_vol_20"]
    cols = []
    for name in CLUSTER_FEATURES:
        if name.startswith("ret_"):
            k = int(name.split("_")[1][:-1])
            with np.errstate(invalid="ignore", divide="ignore"):
                x = (c / np.vstack([np.full((k, c.shape[1]), np.nan), c[:-k]]) - 1) / (
                    hv * np.sqrt(k)
                )
        else:
            x = f[name]
        cols.append(np.asarray(x, dtype="float64").ravel())
    return np.stack(cols, axis=1)


def fit_clusters(
    train: Arr, k: int, seed: int = 0, max_rows: int = 200_000, method: str = "kmeans"
) -> ClusterModel:
    """Fit scaler + K-Means (or a Gaussian mixture, method="gmm", full covariance) on TRAINING rows only (rows with any NaN are dropped; a fixed-seed subsample caps the size)."""
    x = train[np.isfinite(train).all(1)]
    if len(x) > max_rows:
        x = x[np.random.default_rng(seed).choice(len(x), max_rows, replace=False)]
    mean, std = x.mean(0), x.std(0)
    std = np.where(std > 0, std, 1.0)
    z = (x - mean) / std
    if method == "gmm":
        km = GaussianMixture(
            n_components=k, covariance_type="full", n_init=3, random_state=seed, reg_covar=1e-4
        ).fit(z)
    elif method == "kmeans":
        km = KMeans(n_clusters=k, n_init=10, random_state=seed).fit(z)
    else:
        raise ValueError(f"unknown clustering method {method!r}")
    return ClusterModel(mean, std, km, k, seed)


def assign_clusters(m: ClusterModel, x: Arr) -> Arr:
    """Cluster id per row using the TRAINING scaler and centres; -1 where a row has NaN."""
    ok = np.isfinite(x).all(1)
    out = np.full(len(x), -1, dtype="int16")
    if ok.any():
        out[ok] = m.km.predict((x[ok] - m.mean) / m.std)
    return out
