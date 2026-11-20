# ruff: noqa: E501
"""ATI P1: the technical feature library (spec sections 4.1 to 4.6). Continuous values only, no buy/sell labels.

Layout as `algo.research.winner_features`: inputs are days x stocks float arrays of ADJUSTED prices (NaN where a stock has no bar);
a feature at row t uses sessions <= t only (known at the close of t). NaN stays NaN (warm-up, missing bars).
Changing any formula or look-back means bumping FEATURE_VERSION: a new version never overwrites an old research output.
The SuperTrend grid is generated as separate features per (ATR period, multiplier); none is picked by historical profit (selection bias).
Pure functions of the arrays: no clock, no I/O."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import numpy as np
import pandas as pd

from algo.research.winner_features import CAP, FeatureMeta, _Ctx, _rsi

Arr = np.ndarray[Any, Any]
FEATURE_VERSION = "ati-f1"
GROUPS = ("trend", "momentum", "volatility", "volume", "channel", "supertrend")
ST_PERIODS = (7, 10, 14, 20, 21)
ST_MULTS = (1.5, 2.0, 2.5, 3.0, 3.5, 4.0)
EMAS = (5, 10, 20, 50, 100, 200)
SMAS = (20, 50, 200)
SLOPE_K = 5  # slope = ema[t] / ema[t-5] - 1

_REG: list[tuple[FeatureMeta, Callable[..., pd.DataFrame]]] = []


def _f(
    name: str, group: str, lookback: int, description: str, fn: Callable[..., pd.DataFrame]
) -> None:
    _REG.append((FeatureMeta(name, group, description, lookback, group == "volatility"), fn))


def _atr(x: _Ctx, n: int) -> pd.DataFrame:
    """Wilder ATR (RMA of the true range); NaN until n true ranges exist."""
    return x.memo(("atr_w", n), lambda: x.tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean())


def _hi(x: _Ctx, n: int) -> pd.DataFrame:
    return x.h.rolling(n, min_periods=n).max()


def _lo(x: _Ctx, n: int) -> pd.DataFrame:
    return x.l.rolling(n, min_periods=n).min()


def _width20(x: _Ctx) -> pd.DataFrame:
    return (_hi(x, 20) - _lo(x, 20)) / x.c


def _macd(x: _Ctx) -> pd.DataFrame:
    return x.ema(12) - x.ema(26)


def _cmf(x: _Ctx) -> pd.DataFrame:
    rng = (x.h - x.l).where(x.h > x.l)
    mfv = ((x.c - x.l) - (x.h - x.c)) / rng * x.v
    return mfv.rolling(20, min_periods=20).sum() / x.v.rolling(20, min_periods=20).sum()


# ---- 4.1 trend ----
for _n in EMAS:
    _f(
        f"ema_{_n}_distance",
        "trend",
        _n,
        f"(close - EMA{_n}) / EMA{_n}",
        lambda x, n=_n: (x.c - x.ema(n)) / x.ema(n),
    )
for _n in (20, 50, 200):
    _f(
        f"ema_{_n}_slope",
        "trend",
        _n + SLOPE_K,
        f"EMA{_n} / EMA{_n} {SLOPE_K} sessions ago - 1",
        lambda x, n=_n: x.ema(n) / x.ema(n).shift(SLOPE_K) - 1,
    )
for _n in SMAS:
    _f(
        f"sma_{_n}_distance",
        "trend",
        _n,
        f"(close - SMA{_n}) / SMA{_n}",
        lambda x, n=_n: (x.c - x.sma(n)) / x.sma(n),
    )
_f(
    "ema_20_50_spread",
    "trend",
    50,
    "(EMA20 - EMA50) / EMA50",
    lambda x: (x.ema(20) - x.ema(50)) / x.ema(50),
)
_f(
    "ema_50_200_spread",
    "trend",
    200,
    "(EMA50 - EMA200) / EMA200",
    lambda x: (x.ema(50) - x.ema(200)) / x.ema(200),
)
_f(
    "ema_bullish_alignment",
    "trend",
    200,
    "1 if close > EMA20 > EMA50 > EMA200 else 0 (NaN in warm-up)",
    lambda x: (
        ((x.c > x.ema(20)) & (x.ema(20) > x.ema(50)) & (x.ema(50) > x.ema(200)))
        .astype(float)
        .where(x.sma(200).notna())
    ),
)
_f(
    "ema_bearish_alignment",
    "trend",
    200,
    "1 if close < EMA20 < EMA50 < EMA200 else 0 (NaN in warm-up)",
    lambda x: (
        ((x.c < x.ema(20)) & (x.ema(20) < x.ema(50)) & (x.ema(50) < x.ema(200)))
        .astype(float)
        .where(x.sma(200).notna())
    ),
)

# ---- 4.2 momentum ----
for _n in (7, 14, 21):
    _f(
        f"rsi_{_n}",
        "momentum",
        _n + 1,
        f"Wilder RSI({_n}), 0-100",
        lambda x, n=_n: x.memo(("rsi", n), lambda: _rsi(x.c, n)).where(
            x.c.rolling(n + 1).count() == n + 1
        ),
    )
_f("macd_line", "momentum", 26, "(EMA12 - EMA26) / close", lambda x: _macd(x) / x.c)
_f(
    "macd_histogram",
    "momentum",
    35,
    "(MACD - its 9-EMA) / close, price-normalised",
    lambda x: (_macd(x) - _macd(x).ewm(span=9, adjust=False).mean()) / x.c,
)
_f("roc_10", "momentum", 11, "close / close 10 sessions ago - 1", lambda x: x.ret(10))
for _n in (5, 10, 20):
    _f(
        f"momentum_{_n}",
        "momentum",
        _n + 1,
        f"(close - close {_n} sessions ago) / close",
        lambda x, n=_n: (x.c - x.c.shift(n)) / x.c,
    )
_f(
    "stoch_k_14",
    "momentum",
    14,
    "Stochastic %K(14), 0-100",
    lambda x: 100 * (x.c - _lo(x, 14)) / (_hi(x, 14) - _lo(x, 14)),
)
_f(
    "williams_r_14",
    "momentum",
    14,
    "Williams %R(14), -100..0",
    lambda x: -100 * (_hi(x, 14) - x.c) / (_hi(x, 14) - _lo(x, 14)),
)

# ---- 4.3 volatility ----
for _n in (7, 14, 21):
    _f(
        f"atr_pct_{_n}",
        "volatility",
        _n + 1,
        f"Wilder ATR({_n}) / close * 100",
        lambda x, n=_n: _atr(x, n) / x.c * 100,
    )
_f("bb_width_20", "volatility", 20, "(upper - lower) / middle of Bollinger(20, 2)", lambda x: x.bw)
_f(
    "bb_position_20",
    "volatility",
    20,
    "(close - lower) / (upper - lower) of Bollinger(20, 2), 0-1 inside the bands",
    lambda x: 0.5 + (x.c - x.sma(20)) / (4 * x.c.rolling(20, min_periods=20).std()),
)
_f("hist_vol_20", "volatility", 21, "stdev of 20 daily returns", lambda x: x.vol(20))
_f(
    "vol_percentile_252",
    "volatility",
    273,
    "rank of hist_vol_20 within its last 252 values (0-1)",
    lambda x: x.vol(20).rolling(252, min_periods=126).rank(pct=True),
)
_f(
    "vol_expansion",
    "volatility",
    35,
    "ATR14 / ATR14 20 sessions ago (>1 = expanding)",
    lambda x: _atr(x, 14) / _atr(x, 14).shift(20),
)
_f(
    "vol_contraction",
    "volatility",
    74,
    "ATR14 / its 60-session maximum (small = contracted)",
    lambda x: _atr(x, 14) / _atr(x, 14).rolling(60, min_periods=40).max(),
)

# ---- 4.4 volume ----
for _n in (5, 10, 20):
    _f(
        f"volume_sma_{_n}",
        "volume",
        _n,
        f"mean volume of the last {_n} sessions (incl. today)",
        lambda x, n=_n: x.v.rolling(n, min_periods=n).mean(),
    )
_f(
    "relative_volume",
    "volume",
    20,
    "volume / SMA20 volume (incl. today)",
    lambda x: x.v / x.v.rolling(20, min_periods=20).mean(),
)
_f(
    "volume_acceleration",
    "volume",
    20,
    "SMA5 volume / SMA20 volume",
    lambda x: x.v.rolling(5, min_periods=5).mean() / x.v.rolling(20, min_periods=20).mean(),
)
_f(
    "obv_slope_20",
    "volume",
    21,
    "OBV change over 20 sessions / (20 * SMA20 volume)",
    lambda x: (
        ((x.c.diff().gt(0).astype(float) - x.c.diff().lt(0).astype(float)) * x.v).cumsum().diff(20)
        / (x.v.rolling(20, min_periods=20).mean() * 20)
    ),
)
_f("cmf_20", "volume", 20, "Chaikin money flow(20), -1..1", _cmf)
_f(
    "volume_price_corr_20",
    "volume",
    21,
    "correlation of volume and |return| over 20 sessions",
    lambda x: x.v.rolling(20, min_periods=20).corr(x.ret(1).abs()),
)

# ---- 4.5 channels and breakout ----
for _n in (20, 55):
    _f(
        f"distance_to_{_n}d_high",
        "channel",
        _n,
        f"close / highest high of the last {_n} sessions (incl. today) - 1 (<= 0)",
        lambda x, n=_n: x.c / _hi(x, n) - 1,
    )
_f(
    "distance_to_20d_low",
    "channel",
    20,
    "close / lowest low of the last 20 sessions (incl. today) - 1 (>= 0)",
    lambda x: x.c / _lo(x, 20) - 1,
)
_f(
    "breakout_distance",
    "channel",
    21,
    "close / highest high of the PREVIOUS 20 sessions - 1 (>0 = Donchian-20 breakout)",
    lambda x: x.c / x.h.shift(1).rolling(20, min_periods=20).max() - 1,
)
_f("channel_width_20", "channel", 20, "(Donchian20 high - low) / close", _width20)
_f(
    "channel_position_55",
    "channel",
    55,
    "(close - Donchian55 low) / (high - low), 0-1",
    lambda x: (x.c - _lo(x, 55)) / (_hi(x, 55) - _lo(x, 55)),
)
_f(
    "keltner_position_20",
    "channel",
    21,
    "(close - EMA20) / (2 * ATR10): -1..1 inside Keltner(20, 10, 2)",
    lambda x: (x.c - x.ema(20)) / (2 * _atr(x, 10)),
)
_f(
    "compression_score",
    "channel",
    79,
    "channel_width_20 / its 60-session median (small = compressed)",
    lambda x: _width20(x) / _width20(x).rolling(60, min_periods=40).median(),
)


# ---- 4.6 SuperTrend grid ----
def supertrend(h: Arr, lo: Arr, c: Arr, atr: Arr, mult: float) -> tuple[Arr, Arr]:
    """(direction +1/-1, line) as days x stocks. Final bands only ratchet while the previous close stayed on the same side; the direction flips when the
    close crosses the opposite final band. NaN until the ATR exists. Row t depends on rows <= t only."""
    t, s = c.shape
    d = np.full((t, s), np.nan)
    line = np.full((t, s), np.nan)
    up = np.full(s, np.nan)  # final upper band: the line while the direction is down
    dn = np.full(s, np.nan)  # final lower band: the line while the direction is up
    dirn = np.full(s, np.nan)
    for i in range(t):
        mid = (h[i] + lo[i]) / 2
        bu, bl = mid + mult * atr[i], mid - mult * atr[i]
        ok = np.isfinite(bu) & np.isfinite(bl) & np.isfinite(c[i])
        started = np.isfinite(dirn)
        pc = c[i - 1] if i else np.full(s, np.nan)
        nu = np.where(started & (bu >= up) & (pc <= up), up, bu)
        nl = np.where(started & (bl <= dn) & (pc >= dn), dn, bl)
        nd = np.where(
            ~started,
            1.0,
            np.where((dirn < 0) & (c[i] > nu), 1.0, np.where((dirn > 0) & (c[i] < nl), -1.0, dirn)),
        )
        up, dn, dirn = np.where(ok, nu, up), np.where(ok, nl, dn), np.where(ok, nd, dirn)
        d[i] = np.where(ok, dirn, np.nan)
        line[i] = np.where(ok, np.where(dirn > 0, dn, up), np.nan)
    return d, line


def _st(x: _Ctx, n: int, m: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    def run() -> pd.DataFrame:
        d, line = supertrend(
            x.h.to_numpy(), x.l.to_numpy(), x.c.to_numpy(), _atr(x, n).to_numpy(), m
        )
        return pd.concat({"d": pd.DataFrame(d), "line": pd.DataFrame(line)}, axis=1)

    both = x.memo(("st", n, m), run)
    return pd.DataFrame(both["d"]), pd.DataFrame(both["line"])


def _flip(x: _Ctx, n: int, m: float) -> pd.DataFrame:
    d = _st(x, n, m)[0]
    return (d.diff().abs() > 0).astype(float).where(d.diff().notna())


for _n in ST_PERIODS:
    for _m in ST_MULTS:
        _k = f"st_{_n}_{str(_m).replace('.', '_')}"
        _f(
            f"{_k}_direction",
            "supertrend",
            _n + 1,
            f"SuperTrend(ATR {_n}, x{_m}) direction: +1 up, -1 down",
            lambda x, n=_n, m=_m: _st(x, n, m)[0],
        )
        _f(
            f"{_k}_distance",
            "supertrend",
            _n + 1,
            f"(close - SuperTrend line) / close, ATR {_n} x{_m}",
            lambda x, n=_n, m=_m: (x.c - _st(x, n, m)[1]) / x.c,
        )
        _f(
            f"{_k}_flip",
            "supertrend",
            _n + 2,
            f"1 on the session the direction changed, else 0, ATR {_n} x{_m}",
            lambda x, n=_n, m=_m: _flip(x, n, m),
        )
        _f(
            f"{_k}_signal_age",
            "supertrend",
            _n + 2,
            f"sessions since the last flip (0 on the flip day), capped at {CAP}, ATR {_n} x{_m}",
            lambda x, n=_n, m=_m: x.since(_flip(x, n, m) > 0).where(_st(x, n, m)[0].notna()),
        )

META: dict[str, FeatureMeta] = {m.name: m for m, _ in _REG}
assert len(META) == len(_REG), "duplicate feature name"


def compute_features(
    o: Arr, h: Arr, lo: Arr, c: Arr, v: Arr, groups: tuple[str, ...] | None = None
) -> Iterator[tuple[FeatureMeta, Arr]]:
    """Yield (meta, days x stocks float32 array) one feature at a time; rows before the documented look-back are NaN."""
    ctx = _Ctx(o, h, lo, c, v, np.zeros_like(np.asarray(v, dtype="float64")))
    for meta, fn in _REG:
        if groups is not None and meta.group not in groups:
            continue
        out = fn(ctx).to_numpy(dtype="float64", copy=True)
        out[: meta.lookback - 1] = (
            np.nan
        )  # recursive filters (EMA) emit values from row 0: blank everything before the documented look-back
        yield meta, np.where(np.isfinite(out), out, np.nan).astype("float32")
