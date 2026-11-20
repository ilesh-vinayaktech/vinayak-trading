# ruff: noqa: E501
"""Feature engineering V2 for the early-large-upside research (V2 spec, Phase B): price structure, volume and delivery, volatility, early-opportunity, plus the 24 V1 features.

Layout: inputs are days x stocks float arrays of ADJUSTED prices, volume and delivery quantity (NaN where a stock has no bar). A feature at row t uses data of sessions <= t only
(the signal is taken after the close of t); cross-sectional features (ranks, medians, breadth) use only the same day's other stocks. Windows that need a previous reference
(a "previous 20-session high") exclude today. Where a feature is NaN (warm-up, missing bars) it stays NaN: tree models take it as missing. `META` documents every feature.
Groups: v1 (the 24 features of WINNER_V1, kept exactly), price (A), volume (B), volatility (C), early (F). Market and sector context (D, E) are Phase C.
`META[name].volatility` marks the volatility features, including the three V1 ones (vol60, bwr, rng15), so an experiment can drop volatility as a whole.
Pure functions of the arrays: no clock, no I/O."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

Arr = np.ndarray[Any, Any]
GROUPS = ("v1", "price", "volume", "volatility", "early")
CAP = 60  # "sessions since" features are capped here (no such event in the last 60 sessions)


@dataclass(frozen=True)
class FeatureMeta:
    name: str
    group: str
    description: str
    lookback: int
    volatility: bool
    source: str = "bar_1d: Kite adjusted OHLCV (delivery quantity from the NSE bhavcopy)"
    available: str = "close of session t"
    missing: str = "NaN until the look-back is filled or when a bar is missing; tree models treat NaN as missing"


class _Ctx:
    """The shared building blocks of the features, each computed once."""

    def __init__(self, o: Arr, h: Arr, lo: Arr, c: Arr, v: Arr, dq: Arr) -> None:
        d = {
            k: pd.DataFrame(np.asarray(a, dtype="float64"))
            for k, a in (("o", o), ("h", h), ("l", lo), ("c", c), ("v", v), ("dq", dq))
        }
        self.o, self.h, self.l, self.c, self.v, self.dq = (
            d[k] for k in ("o", "h", "l", "c", "v", "dq")
        )
        self.t, self.s = self.c.shape
        self._m: dict[Any, pd.DataFrame] = {}

    def memo(self, key: Any, fn: Callable[[], pd.DataFrame]) -> pd.DataFrame:
        if key not in self._m:
            self._m[key] = fn()
        return self._m[key]

    def ret(self, k: int) -> pd.DataFrame:
        return self.memo(("ret", k), lambda: self.c / self.c.shift(k) - 1)

    @property
    def pc(self) -> pd.DataFrame:
        return self.memo("pc", lambda: self.c.shift(1))

    @property
    def tr(self) -> pd.DataFrame:
        return self.memo(
            "tr",
            lambda: pd.DataFrame(
                np.fmax.reduce(
                    [
                        (self.h - self.l).to_numpy(),
                        (self.h - self.pc).abs().to_numpy(),
                        (self.l - self.pc).abs().to_numpy(),
                    ]
                )
            ),
        )

    @property
    def atr14(self) -> pd.DataFrame:
        return self.memo("atr14", lambda: self.tr.rolling(14, min_periods=14).mean())

    @property
    def atr60(self) -> pd.DataFrame:
        return self.memo("atr60", lambda: self.tr.rolling(60, min_periods=40).mean())

    def ema(self, n: int) -> pd.DataFrame:
        return self.memo(("ema", n), lambda: self.c.ewm(span=n, adjust=False).mean())

    def sma(self, n: int) -> pd.DataFrame:
        return self.memo(("sma", n), lambda: self.c.rolling(n, min_periods=n).mean())

    def vol(self, n: int) -> pd.DataFrame:
        return self.memo(
            ("vol", n), lambda: self.ret(1).rolling(n, min_periods=int(n * 0.75)).std()
        )

    @property
    def vm20(self) -> pd.DataFrame:  # the PREVIOUS 20 sessions' average volume
        return self.memo("vm20", lambda: self.v.shift(1).rolling(20, min_periods=15).mean())

    @property
    def vr1(self) -> pd.DataFrame:
        return self.memo("vr1", lambda: self.v / self.vm20)

    @property
    def dpct(self) -> pd.DataFrame:
        return self.memo("dpct", lambda: self.dq / self.v.where(self.v > 0) * 100)

    @property
    def bw(self) -> pd.DataFrame:  # Bollinger band width (4 sd over the 20-day mean)
        return self.memo("bw", lambda: 4 * self.c.rolling(20, min_periods=20).std() / self.sma(20))

    @property
    def breakout(self) -> pd.DataFrame:  # close above the previous 20 sessions' high
        def f() -> pd.DataFrame:
            ref = self.h.shift(1).rolling(20, min_periods=20).max()
            return (self.c > ref).where(ref.notna(), False)

        return self.memo("bk", f)

    @property
    def turnover(self) -> pd.DataFrame:
        return self.memo("turn", lambda: (self.c * self.v).rolling(20, min_periods=15).mean() / 1e7)

    def since(self, flag: pd.DataFrame) -> pd.DataFrame:
        """Sessions since `flag` was last True (0 on that day), capped at CAP (also when it never was)."""
        t = np.arange(self.t)[:, None]
        last = pd.DataFrame(np.where(flag.to_numpy(dtype=bool), t, np.nan)).ffill()
        return pd.DataFrame(t - last.to_numpy()).fillna(CAP).clip(upper=CAP)

    def broadcast(self, s: pd.Series) -> pd.DataFrame:
        return pd.DataFrame(np.repeat(s.to_numpy()[:, None], self.s, axis=1))


_REG: list[tuple[FeatureMeta, Callable[[_Ctx], pd.DataFrame]]] = []


def _f(
    name: str,
    group: str,
    lookback: int,
    description: str,
    fn: Callable[[_Ctx], pd.DataFrame],
    *,
    vol: bool = False,
) -> None:
    _REG.append((FeatureMeta(name, group, description, lookback, vol or group == "volatility"), fn))


def _rsi(c: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    d = c.diff()
    return 100 - 100 / (
        1
        + d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
        / (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    )


def _ret(k: int) -> Callable[[_Ctx], pd.DataFrame]:
    return lambda x: x.ret(k)


def _dist_ema(n: int) -> Callable[[_Ctx], pd.DataFrame]:
    return lambda x: (x.c - x.ema(n)) / x.atr14


def _vol(n: int) -> Callable[[_Ctx], pd.DataFrame]:
    return lambda x: x.vol(n)


def _mfe(n: int) -> Callable[[_Ctx], pd.DataFrame]:
    return lambda x: x.h.rolling(n).max() / x.c.shift(n) - 1


def _mae(n: int) -> Callable[[_Ctx], pd.DataFrame]:
    return lambda x: x.l.rolling(n).min() / x.c.shift(n) - 1


def _updown(x: _Ctx, up: bool) -> pd.DataFrame:
    return x.v.where(x.c > x.pc if up else x.c < x.pc, 0).rolling(10).sum()


# ---------------------------------------------------------------- v1: the 24 features of WINNER_V1 (definitions as in scripts/study_winners_first.py)
_f("r1", "v1", 1, "close / previous close - 1", lambda x: x.ret(1))
_f("r5", "v1", 5, "5-session return", lambda x: x.ret(5))
_f("r20", "v1", 20, "20-session return", lambda x: x.ret(20))
_f("r60", "v1", 60, "60-session return", lambda x: x.ret(60))
_f(
    "rng15",
    "v1",
    15,
    "(15-session high - low) / close: a range, so a volatility feature",
    lambda x: (x.h.rolling(15).max() - x.l.rolling(15).min()) / x.c,
    vol=True,
)
_f(
    "bwr",
    "v1",
    180,
    "Bollinger width / its own 120-session mean: a volatility feature",
    lambda x: x.bw / x.bw.rolling(120, min_periods=60).mean(),
    vol=True,
)
_f("vr1", "v1", 21, "volume / mean volume of the previous 20 sessions", lambda x: x.vr1)
_f(
    "vr5",
    "v1",
    25,
    "5-session mean volume / mean of the 20 sessions before those",
    lambda x: x.v.rolling(5).mean() / x.v.shift(5).rolling(20, min_periods=15).mean(),
)
_f(
    "dlv_gap",
    "v1",
    20,
    "delivery % over 5 sessions minus over 20 sessions (points)",
    lambda x: (
        x.dq.rolling(5).sum() / x.v.rolling(5).sum() * 100
        - x.dq.rolling(20, min_periods=15).sum() / x.v.rolling(20, min_periods=15).sum() * 100
    ),
)
_f(
    "dpct5",
    "v1",
    5,
    "delivery % over 5 sessions",
    lambda x: x.dq.rolling(5).sum() / x.v.rolling(5).sum() * 100,
)
_f("rsi14", "v1", 14, "RSI(14), Wilder smoothing", lambda x: _rsi(x.c))
_f("g50", "v1", 50, "close / SMA50 - 1", lambda x: x.c / x.sma(50) - 1)
_f("g200", "v1", 200, "close / SMA200 - 1", lambda x: x.c / x.sma(200) - 1)
_f(
    "d20h",
    "v1",
    21,
    "close / previous 20-session high - 1",
    lambda x: x.c / x.h.shift(1).rolling(20, min_periods=20).max() - 1,
)
_f(
    "d252h",
    "v1",
    200,
    "close / 252-session high - 1",
    lambda x: x.c / x.h.rolling(252, min_periods=200).max() - 1,
)
_f(
    "loc",
    "v1",
    1,
    "(close - low) / (high - low)",
    lambda x: (x.c - x.l) / (x.h - x.l).where((x.h - x.l) > 0),
)
_f(
    "rel20",
    "v1",
    20,
    "20-session return minus the day's median 20-session return",
    lambda x: x.ret(20).sub(x.ret(20).median(axis=1), axis=0),
)
_f(
    "rk_r20",
    "v1",
    20,
    "same-day percentile rank of the 20-session return",
    lambda x: x.ret(20).rank(axis=1, pct=True),
)
_f(
    "rk_vr5",
    "v1",
    25,
    "same-day percentile rank of vr5",
    lambda x: (x.v.rolling(5).mean() / x.v.shift(5).rolling(20, min_periods=15).mean()).rank(
        axis=1, pct=True
    ),
)
_f(
    "mk5",
    "v1",
    5,
    "median 5-session return of all stocks that day (market context)",
    lambda x: x.broadcast(x.ret(5).median(axis=1)),
)
_f(
    "mk20",
    "v1",
    20,
    "median 20-session return of all stocks that day (market context)",
    lambda x: x.broadcast(x.ret(20).median(axis=1)),
)
_f(
    "breadth50",
    "v1",
    50,
    "share of stocks above their SMA50 that day (market context)",
    lambda x: x.broadcast((x.c > x.sma(50)).where(x.sma(50).notna()).mean(axis=1)),
)
_f(
    "lturn",
    "v1",
    20,
    "log of the 20-session mean traded value (Rs crore)",
    lambda x: pd.DataFrame(np.log(x.turnover + 1e-9)),
)
_f(
    "vol60",
    "v1",
    60,
    "60-session std of daily returns, in %: a volatility feature",
    lambda x: x.ret(1).rolling(60, min_periods=40).std() * 100,
    vol=True,
)

# ---------------------------------------------------------------- group A: price structure
for _k in (1, 3, 5, 10, 20, 60):
    _f(f"ret_{_k}d", "price", _k, f"close / close {_k} sessions ago - 1", _ret(_k))
for _n in (20, 50, 200):
    _f(
        f"dist_ema{_n}_atr",
        "price",
        _n,
        f"(close - EMA{_n}) / ATR14",
        _dist_ema(_n),
    )
_f(
    "dist_high20_pct",
    "price",
    21,
    "close / previous 20-session high - 1 (today excluded)",
    lambda x: x.c / x.h.shift(1).rolling(20, min_periods=20).max() - 1,
)
_f(
    "dist_high52w_pct",
    "price",
    200,
    "close / previous 252-session high - 1 (today excluded)",
    lambda x: x.c / x.h.shift(1).rolling(252, min_periods=200).max() - 1,
)
_f(
    "dist_low20_pct",
    "price",
    21,
    "close / previous 20-session low - 1 (today excluded)",
    lambda x: x.c / x.l.shift(1).rolling(20, min_periods=20).min() - 1,
)
_f(
    "higher_high_count_10d",
    "price",
    11,
    "sessions in the last 10 whose high exceeded the previous session's high",
    lambda x: (x.h > x.h.shift(1)).where(x.h.shift(1).notna()).rolling(10).sum(),
)
_f(
    "higher_low_count_10d",
    "price",
    11,
    "sessions in the last 10 whose low exceeded the previous session's low",
    lambda x: (x.l > x.l.shift(1)).where(x.l.shift(1).notna()).rolling(10).sum(),
)
_f(
    "positive_close_count_5d",
    "price",
    6,
    "up-close sessions in the last 5",
    lambda x: (x.c > x.pc).where(x.pc.notna()).rolling(5).sum(),
)
_f(
    "positive_close_count_10d",
    "price",
    11,
    "up-close sessions in the last 10",
    lambda x: (x.c > x.pc).where(x.pc.notna()).rolling(10).sum(),
)
_f(
    "close_range_position",
    "price",
    1,
    "(close - low) / (high - low)",
    lambda x: (x.c - x.l) / (x.h - x.l).where((x.h - x.l) > 0),
)
_f(
    "pullback_from_high_10d",
    "price",
    10,
    "close / highest high of the last 10 sessions - 1",
    lambda x: x.c / x.h.rolling(10).max() - 1,
)
_f(
    "breakout_age",
    "price",
    81,
    f"sessions since the last close above the previous 20-session high (0 = today; {CAP} = none in {CAP})",
    lambda x: x.since(x.breakout),
)

# ---------------------------------------------------------------- group B: volume and delivery
_f(
    "volume_ratio_1d",
    "volume",
    21,
    "volume / mean volume of the previous 20 sessions",
    lambda x: x.vr1,
)
_f(
    "volume_ratio_5d",
    "volume",
    25,
    "5-session mean volume / mean volume of the 20 sessions before those",
    lambda x: x.v.rolling(5).mean() / x.v.shift(5).rolling(20, min_periods=15).mean(),
)
_f(
    "volume_ratio_20d",
    "volume",
    80,
    "20-session mean volume / mean of the 60 sessions before those",
    lambda x: (
        x.v.rolling(20, min_periods=15).mean() / x.v.shift(20).rolling(60, min_periods=40).mean()
    ),
)
_f("delivery_pct", "volume", 1, "delivered quantity / traded quantity, in %", lambda x: x.dpct)
_f(
    "delivery_pct_change_5d",
    "volume",
    21,
    "today's delivery % minus the mean of the previous 20 sessions (spec wording; the _5d in the name is the spec's)",
    lambda x: x.dpct - x.dpct.shift(1).rolling(20, min_periods=15).mean(),
)
_f(
    "delivery_qty_ratio",
    "volume",
    21,
    "delivered quantity / mean delivered quantity of the previous 20 sessions",
    lambda x: x.dq / x.dq.shift(1).rolling(20, min_periods=15).mean(),
)
_f(
    "up_volume_ratio_10d",
    "volume",
    11,
    "volume on up-close sessions / total volume, last 10 sessions",
    lambda x: _updown(x, True) / x.v.rolling(10).sum(),
)
_f(
    "down_volume_ratio_10d",
    "volume",
    11,
    "volume on down-close sessions / total volume, last 10 sessions",
    lambda x: _updown(x, False) / x.v.rolling(10).sum(),
)
_f(
    "up_down_volume_ratio",
    "volume",
    11,
    "up-session volume / down-session volume, last 10 sessions (NaN with no down session)",
    lambda x: _updown(x, True) / _updown(x, False).where(_updown(x, False) > 0),
)
_f(
    "price_volume_confirmation",
    "volume",
    21,
    "sign(1-session return) x log(volume_ratio_1d): a move on more volume is positive",
    lambda x: np.sign(x.ret(1)) * np.log(x.vr1.where(x.vr1 > 0)),
)
_f(
    "pullback_volume_ratio",
    "volume",
    25,
    "mean volume of the down-close sessions of the last 5 / mean volume of the 20 sessions before those (NaN with none)",
    lambda x: (
        x.v.where(x.c < x.pc).rolling(5, min_periods=1).mean()
        / x.v.shift(5).rolling(20, min_periods=15).mean()
    ),
)
_f(
    "breakout_volume_ratio",
    "volume",
    81,
    "volume_ratio_1d on the most recent breakout session, carried for up to 60 sessions",
    lambda x: x.vr1.where(x.breakout).ffill(limit=CAP),
)

# ---------------------------------------------------------------- group C: volatility and expansion
_f("atr_pct_14", "volatility", 14, "ATR14 / close", lambda x: x.atr14 / x.c)
_f("atr_pct_60", "volatility", 60, "ATR60 / close", lambda x: x.atr60 / x.c)
_f(
    "atr_percentile_252",
    "volatility",
    252,
    "rank of ATR14/close within its own last 252 sessions",
    lambda x: (x.atr14 / x.c).rolling(252, min_periods=120).rank(pct=True),
)
for _n in (5, 10, 20, 60):
    _f(
        f"volatility_{_n}d",
        "volatility",
        _n,
        f"std of daily returns over {_n} sessions",
        _vol(_n),
    )
_f(
    "volatility_ratio",
    "volatility",
    60,
    "volatility_10d / volatility_60d",
    lambda x: x.vol(10) / x.vol(60),
)
_f(
    "bb_width_percentile",
    "volatility",
    252,
    "rank of Bollinger width within its own last 252 sessions",
    lambda x: x.bw.rolling(252, min_periods=120).rank(pct=True),
)
_f(
    "range_expansion_5d",
    "volatility",
    25,
    "mean (high - low) of the last 5 sessions / mean of the 20 before those",
    lambda x: (
        (x.h - x.l).rolling(5).mean() / (x.h - x.l).shift(5).rolling(20, min_periods=15).mean()
    ),
)
_f(
    "gap_frequency_20d",
    "volatility",
    21,
    "share of the last 20 sessions that opened 2%+ away from the previous close",
    lambda x: (
        ((x.o / x.pc - 1).abs() >= 0.02).where(x.pc.notna()).rolling(20, min_periods=15).mean()
    ),
)
_f(
    "gap_magnitude_20d",
    "volatility",
    21,
    "mean absolute opening gap over the last 20 sessions",
    lambda x: (x.o / x.pc - 1).abs().rolling(20, min_periods=15).mean(),
)
_f(
    "ext3",
    "volatility",
    20,
    "1 when close is more than 3 ATR14 above its EMA20, else 0 (as in scripts/study_volatility.py)",
    lambda x: ((x.c - x.ema(20)) > 3 * x.atr14).where(x.atr14.notna()).astype("float64"),
)
_f(
    "atr_expansion",
    "volatility",
    24,
    "ATR14 / ATR14 ten sessions ago - 1",
    lambda x: x.atr14 / x.atr14.shift(10) - 1,
)

# ---------------------------------------------------------------- group F: early opportunity (what the stock has already done, and from where)
_f(
    "distance_from_5d_low",
    "early",
    5,
    "close / lowest low of the last 5 sessions - 1",
    lambda x: x.c / x.l.rolling(5).min() - 1,
)
_f(
    "distance_from_20d_low",
    "early",
    20,
    "close / lowest low of the last 20 sessions - 1",
    lambda x: x.c / x.l.rolling(20).min() - 1,
)
_f(
    "distance_from_20d_high",
    "early",
    20,
    "close / highest high of the last 20 sessions - 1 (today included)",
    lambda x: x.c / x.h.rolling(20).max() - 1,
)
_f(
    "distance_from_52w_high",
    "early",
    200,
    "close / highest high of the last 252 sessions - 1 (today included)",
    lambda x: x.c / x.h.rolling(252, min_periods=200).max() - 1,
)
for _n in (5, 10):
    _f(
        f"mfe_previous_{_n}d",
        "early",
        _n + 1,
        f"highest high of the last {_n} sessions / close {_n} sessions ago - 1",
        _mfe(_n),
    )
    _f(
        f"mae_previous_{_n}d",
        "early",
        _n + 1,
        f"lowest low of the last {_n} sessions / close {_n} sessions ago - 1",
        _mae(_n),
    )
_f(
    "sessions_since_5pct_rise",
    "early",
    66,
    f"sessions since the 5-session return last reached +5% (capped {CAP})",
    lambda x: x.since(x.ret(5) >= 0.05),
)
_f(
    "sessions_since_10pct_rise",
    "early",
    71,
    f"sessions since the 10-session return last reached +10% (capped {CAP})",
    lambda x: x.since(x.ret(10) >= 0.10),
)
_f(
    "consolidation_duration",
    "early",
    80,
    f"consecutive sessions the close stayed within 5% of its 20-session mean (capped {CAP})",
    lambda x: x.since(((x.c / x.sma(20) - 1).abs() > 0.05) | x.sma(20).isna()),
)
_f(
    "pullback_depth_atr",
    "early",
    34,
    "(highest high of the last 20 sessions - close) / ATR14",
    lambda x: (x.h.rolling(20).max() - x.c) / x.atr14,
)

META: dict[str, FeatureMeta] = {m.name: m for m, _ in _REG}
assert len(META) == len(_REG), "duplicate feature name"


def compute_features(
    o: Arr, h: Arr, lo: Arr, c: Arr, v: Arr, dq: Arr, groups: tuple[str, ...] | None = None
) -> Iterator[tuple[FeatureMeta, Arr]]:
    """Yield (meta, days x stocks float32 array) one feature at a time, so a caller can keep only the rows it needs."""
    ctx = _Ctx(o, h, lo, c, v, dq)
    for meta, fn in _REG:
        if groups is not None and meta.group not in groups:
            continue
        out = fn(ctx).to_numpy(dtype="float64")
        yield meta, np.where(np.isfinite(out), out, np.nan).astype("float32")
