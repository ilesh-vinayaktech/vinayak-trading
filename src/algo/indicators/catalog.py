"""The indicator catalogue: what exists, its parameters, and how each is computed.

Each indicator is a pure function of the bars (open, high, low, close, volume as Decimal) and its
parameters, returning named output series aligned to the bars (None = warm-up). The definitions
follow TradingView's so a trader sees the same numbers. The chart and, later, strategies use this
one implementation, so what is plotted is what is tested.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from algo.indicators import core
from algo.indicators.core import ONE, ZERO, Series

HUNDRED = Decimal(100)


@dataclass(frozen=True)
class Bars:
    open: Sequence[Decimal]
    high: Sequence[Decimal]
    low: Sequence[Decimal]
    close: Sequence[Decimal]
    volume: Sequence[Decimal]

    def __len__(self) -> int:
        return len(self.close)


@dataclass(frozen=True)
class Param:
    key: str
    label: str
    default: Decimal
    lo: Decimal
    hi: Decimal
    integer: bool = True


@dataclass(frozen=True)
class Output:
    key: str
    label: str
    kind: str  # line | histogram | dots
    color: str


@dataclass(frozen=True)
class Indicator:
    name: str
    label: str
    group: str
    pane: str  # overlay (on the price chart) | pane (its own pane below)
    description: str
    params: tuple[Param, ...]
    outputs: tuple[Output, ...]
    compute: Callable[[Bars, Mapping[str, Decimal]], dict[str, Series]]
    levels: tuple[Decimal, ...] = ()  # reference lines in a pane (e.g. RSI 30/70)


def P(
    key: str, label: str, default: int | str, lo: int | str, hi: int | str, integer: bool = True
) -> Param:
    return Param(key, label, Decimal(default), Decimal(lo), Decimal(hi), integer)


def _n(p: Mapping[str, Decimal], key: str = "length") -> int:
    return int(p[key])


def _sma(b: Bars, p: Mapping[str, Decimal]) -> dict[str, Series]:
    return {"value": core.sma(b.close, _n(p))}


def _ema(b: Bars, p: Mapping[str, Decimal]) -> dict[str, Series]:
    return {"value": core.ema(b.close, _n(p))}


def _wma(b: Bars, p: Mapping[str, Decimal]) -> dict[str, Series]:
    return {"value": core.wma(b.close, _n(p))}


def _bb(b: Bars, p: Mapping[str, Decimal]) -> dict[str, Series]:
    n, mult = _n(p), p["mult"]
    basis = core.sma(b.close, n)
    dev = core.stdev(b.close, n)
    upper: Series = [
        None if m is None or d is None else m + mult * d for m, d in zip(basis, dev, strict=True)
    ]
    lower: Series = [
        None if m is None or d is None else m - mult * d for m, d in zip(basis, dev, strict=True)
    ]
    return {"basis": basis, "upper": upper, "lower": lower}


def _supertrend(b: Bars, p: Mapping[str, Decimal]) -> dict[str, Series]:
    n, mult = _n(p), p["mult"]
    atr = core.rma(core.true_range(b.high, b.low, b.close), n)
    size = len(b)
    up: Series = [None] * size
    down: Series = [None] * size
    fu: Decimal | None = None  # final upper / lower bands
    fl: Decimal | None = None
    st: str | None = None  # "upper" (downtrend) or "lower" (uptrend)
    for i in range(size):
        a = atr[i]
        if a is None:
            continue
        mid = (b.high[i] + b.low[i]) / 2
        bu, bl = mid + mult * a, mid - mult * a
        pc = b.close[i - 1] if i > 0 else b.close[i]
        nu = bu if fu is None or bu < fu or pc > fu else fu
        nl = bl if fl is None or bl > fl or pc < fl else fl
        if st is None:
            st = "upper"
        elif st == "upper":
            st = "lower" if b.close[i] > nu else "upper"
        else:
            st = "upper" if b.close[i] < nl else "lower"
        fu, fl = nu, nl
        if st == "lower":
            up[i] = nl
        else:
            down[i] = nu
    return {"up": up, "down": down}


def _psar(b: Bars, p: Mapping[str, Decimal]) -> dict[str, Series]:
    start, inc, mx = p["start"], p["inc"], p["max"]
    size = len(b)
    out: Series = [None] * size
    if size < 2:
        return {"value": out}
    rising = b.close[1] >= b.close[0]
    sar = b.low[0] if rising else b.high[0]
    ep = b.high[0] if rising else b.low[0]
    af = start
    out[0] = sar
    for i in range(1, size):
        sar = sar + af * (ep - sar)
        if rising:
            sar = min(sar, b.low[i - 1], b.low[i - 2] if i > 1 else b.low[i - 1])
            if b.low[i] < sar:  # reversal to a downtrend
                rising, sar, ep, af = False, ep, b.low[i], start
            elif b.high[i] > ep:
                ep, af = b.high[i], min(af + inc, mx)
        else:
            sar = max(sar, b.high[i - 1], b.high[i - 2] if i > 1 else b.high[i - 1])
            if b.high[i] > sar:  # reversal to an uptrend
                rising, sar, ep, af = True, ep, b.high[i], start
            elif b.low[i] < ep:
                ep, af = b.low[i], min(af + inc, mx)
        out[i] = sar
    return {"value": out}


def _rsi(b: Bars, p: Mapping[str, Decimal]) -> dict[str, Series]:
    n = _n(p)
    ch = core.change(b.close)
    up: Series = [None if c is None else max(c, ZERO) for c in ch]
    dn: Series = [None if c is None else max(-c, ZERO) for c in ch]
    au, ad = core.rma(up, n), core.rma(dn, n)
    out: Series = []
    for u, d in zip(au, ad, strict=True):
        if u is None or d is None:
            out.append(None)
        elif d == 0:
            out.append(HUNDRED)
        elif u == 0:
            out.append(ZERO)
        else:
            out.append(HUNDRED - HUNDRED / (ONE + u / d))
    return {"value": out}


def _macd(b: Bars, p: Mapping[str, Decimal]) -> dict[str, Series]:
    fast, slow, sig = (
        core.ema(b.close, _n(p, "fast")),
        core.ema(b.close, _n(p, "slow")),
        _n(p, "signal"),
    )
    line: Series = [
        None if f is None or s is None else f - s for f, s in zip(fast, slow, strict=True)
    ]
    signal = core.ema(line, sig)
    hist: Series = [
        None if m is None or s is None else m - s for m, s in zip(line, signal, strict=True)
    ]
    return {"macd": line, "signal": signal, "hist": hist}


def _stoch(b: Bars, p: Mapping[str, Decimal]) -> dict[str, Series]:
    k, d, smooth = _n(p, "k"), _n(p, "d"), _n(p, "smooth")
    hh, ll = core.highest(b.high, k), core.lowest(b.low, k)
    raw: Series = []
    for c, h, lo in zip(b.close, hh, ll, strict=True):
        if h is None or lo is None:
            raw.append(None)
        else:
            raw.append(
                HUNDRED * (c - lo) / (h - lo) if h != lo else Decimal(50)
            )  # a flat range reads 50
    kk = core.sma(raw, smooth)
    return {"k": kk, "d": core.sma(kk, d)}


def _atr(b: Bars, p: Mapping[str, Decimal]) -> dict[str, Series]:
    return {"value": core.rma(core.true_range(b.high, b.low, b.close), _n(p))}


def _adx(b: Bars, p: Mapping[str, Decimal]) -> dict[str, Series]:
    n, smooth = _n(p, "length"), _n(p, "smooth")
    size = len(b)
    plus_dm: Series = [None] * size
    minus_dm: Series = [None] * size
    for i in range(1, size):
        up, dn = b.high[i] - b.high[i - 1], b.low[i - 1] - b.low[i]
        plus_dm[i] = up if up > dn and up > 0 else ZERO
        minus_dm[i] = dn if dn > up and dn > 0 else ZERO
    tr = core.rma(core.true_range(b.high, b.low, b.close), n)
    pdm, mdm = core.rma(plus_dm, n), core.rma(minus_dm, n)
    plus: Series = []
    minus: Series = []
    dx: Series = []
    for t, a, m in zip(tr, pdm, mdm, strict=True):
        if t is None or a is None or m is None or t == 0:
            plus.append(None)
            minus.append(None)
            dx.append(None)
            continue
        pi, mi = HUNDRED * a / t, HUNDRED * m / t
        plus.append(pi)
        minus.append(mi)
        total = pi + mi
        dx.append(abs(pi - mi) / (total if total != 0 else ONE))
    adx: Series = [None if v is None else HUNDRED * v for v in core.rma(dx, smooth)]
    return {"adx": adx, "plus": plus, "minus": minus}


def _cci(b: Bars, p: Mapping[str, Decimal]) -> dict[str, Series]:
    n = _n(p)
    tp: Series = [(h + lo + c) / 3 for h, lo, c in zip(b.high, b.low, b.close, strict=True)]
    mean = core.sma(tp, n)
    out: Series = []
    for i, m in enumerate(mean):
        if m is None:
            out.append(None)
            continue
        dev = sum((abs(v - m) for v in core._values(tp, i - n + 1, i)), ZERO) / n
        cur = tp[i]
        out.append(ZERO if dev == 0 or cur is None else (cur - m) / (Decimal("0.015") * dev))
    return {"value": out}


def _willr(b: Bars, p: Mapping[str, Decimal]) -> dict[str, Series]:
    n = _n(p)
    hh, ll = core.highest(b.high, n), core.lowest(b.low, n)
    out: Series = []
    for c, h, lo in zip(b.close, hh, ll, strict=True):
        if h is None or lo is None:
            out.append(None)
        else:
            out.append(-HUNDRED * (h - c) / (h - lo) if h != lo else Decimal(-50))
    return {"value": out}


def _obv(b: Bars, p: Mapping[str, Decimal]) -> dict[str, Series]:
    out: Series = []
    total = ZERO
    for i in range(len(b)):
        if i > 0:
            if b.close[i] > b.close[i - 1]:
                total += b.volume[i]
            elif b.close[i] < b.close[i - 1]:
                total -= b.volume[i]
        out.append(total)
    return {"value": out}


LENGTH = P("length", "Length", 20, 1, 500)

CATALOG: dict[str, Indicator] = {
    i.name: i
    for i in (
        Indicator(
            "sma",
            "Simple Moving Average",
            "Trend",
            "overlay",
            "Mean of the last N closes.",
            (LENGTH,),
            (Output("value", "SMA", "line", "#2563eb"),),
            compute=_sma,
        ),
        Indicator(
            "ema",
            "Exponential Moving Average",
            "Trend",
            "overlay",
            "Weights recent closes more; seeded with the SMA.",
            (LENGTH,),
            (Output("value", "EMA", "line", "#f59e0b"),),
            compute=_ema,
        ),
        Indicator(
            "wma",
            "Weighted Moving Average",
            "Trend",
            "overlay",
            "Linearly weighted mean of the last N closes.",
            (LENGTH,),
            (Output("value", "WMA", "line", "#7c3aed"),),
            compute=_wma,
        ),
        Indicator(
            "bb",
            "Bollinger Bands",
            "Volatility",
            "overlay",
            "SMA of the close with bands at N population standard deviations.",
            (LENGTH, P("mult", "StdDev", 2, "0.1", 10, False)),
            (
                Output("upper", "Upper", "line", "#2563eb"),
                Output("basis", "Basis", "line", "#f59e0b"),
                Output("lower", "Lower", "line", "#2563eb"),
            ),
            compute=_bb,
        ),
        Indicator(
            "supertrend",
            "Supertrend",
            "Trend",
            "overlay",
            "ATR-based trailing stop that flips with the trend.",
            (P("length", "ATR length", 10, 1, 200), P("mult", "Factor", 3, "0.1", 20, False)),
            (
                Output("up", "Up trend", "line", "#089981"),
                Output("down", "Down trend", "line", "#f23645"),
            ),
            compute=_supertrend,
        ),
        Indicator(
            "psar",
            "Parabolic SAR",
            "Trend",
            "overlay",
            "Wilder's stop-and-reverse dots.",
            (
                P("start", "Start", "0.02", "0.001", "1", False),
                P("inc", "Increment", "0.02", "0.001", "1", False),
                P("max", "Maximum", "0.2", "0.01", "1", False),
            ),
            (Output("value", "SAR", "dots", "#0f172a"),),
            compute=_psar,
        ),
        Indicator(
            "rsi",
            "Relative Strength Index",
            "Momentum",
            "pane",
            "Wilder's RSI of the close (0-100).",
            (P("length", "Length", 14, 1, 200),),
            (Output("value", "RSI", "line", "#7c3aed"),),
            compute=_rsi,
            levels=(Decimal(30), Decimal(70)),
        ),
        Indicator(
            "macd",
            "MACD",
            "Momentum",
            "pane",
            "Fast EMA minus slow EMA, its signal line and the histogram.",
            (
                P("fast", "Fast", 12, 1, 200),
                P("slow", "Slow", 26, 1, 400),
                P("signal", "Signal", 9, 1, 200),
            ),
            (
                Output("hist", "Histogram", "histogram", "#94a3b8"),
                Output("macd", "MACD", "line", "#2563eb"),
                Output("signal", "Signal", "line", "#f59e0b"),
            ),
            compute=_macd,
            levels=(ZERO,),
        ),
        Indicator(
            "stoch",
            "Stochastic",
            "Momentum",
            "pane",
            "Position of the close within the recent high-low range.",
            (
                P("k", "%K length", 14, 1, 200),
                P("d", "%D smoothing", 3, 1, 50),
                P("smooth", "%K smoothing", 3, 1, 50),
            ),
            (Output("k", "%K", "line", "#2563eb"), Output("d", "%D", "line", "#f59e0b")),
            compute=_stoch,
            levels=(Decimal(20), Decimal(80)),
        ),
        Indicator(
            "atr",
            "Average True Range",
            "Volatility",
            "pane",
            "Wilder-smoothed true range.",
            (P("length", "Length", 14, 1, 200),),
            (Output("value", "ATR", "line", "#d97706"),),
            compute=_atr,
        ),
        Indicator(
            "adx",
            "Average Directional Index",
            "Trend",
            "pane",
            "Trend strength with +DI and -DI.",
            (P("length", "DI length", 14, 1, 200), P("smooth", "ADX smoothing", 14, 1, 200)),
            (
                Output("adx", "ADX", "line", "#f23645"),
                Output("plus", "+DI", "line", "#089981"),
                Output("minus", "-DI", "line", "#2563eb"),
            ),
            compute=_adx,
            levels=(Decimal(20), Decimal(25)),
        ),
        Indicator(
            "cci",
            "Commodity Channel Index",
            "Momentum",
            "pane",
            "Typical price against its mean deviation.",
            (P("length", "Length", 20, 1, 300),),
            (Output("value", "CCI", "line", "#0891b2"),),
            compute=_cci,
            levels=(Decimal(-100), Decimal(100)),
        ),
        Indicator(
            "willr",
            "Williams %R",
            "Momentum",
            "pane",
            "Close against the recent high, inverted (-100 to 0).",
            (P("length", "Length", 14, 1, 200),),
            (Output("value", "%R", "line", "#db2777"),),
            compute=_willr,
            levels=(Decimal(-80), Decimal(-20)),
        ),
        Indicator(
            "obv",
            "On Balance Volume",
            "Volume",
            "pane",
            "Running total of volume signed by the close's direction.",
            (),
            (Output("value", "OBV", "line", "#0f172a"),),
            compute=_obv,
        ),
    )
}


class IndicatorError(ValueError):
    pass


def parse_spec(spec: str) -> tuple[Indicator, dict[str, Decimal]]:
    """`name` or `name:arg1:arg2...` (positional, in the catalogue's parameter order)."""
    name, *args = spec.strip().split(":")
    ind = CATALOG.get(name)
    if ind is None:
        raise IndicatorError(f"unknown indicator {name!r}")
    if len(args) > len(ind.params):
        raise IndicatorError(f"{name} takes at most {len(ind.params)} parameters")
    values: dict[str, Decimal] = {}
    for i, prm in enumerate(ind.params):
        if i < len(args) and args[i] != "":
            try:
                v = Decimal(args[i])
            except ArithmeticError as e:
                raise IndicatorError(f"{name}: {prm.label} must be a number") from e
            if not v.is_finite() or (prm.integer and v != v.to_integral_value()):
                raise IndicatorError(
                    f"{name}: {prm.label} must be {'a whole number' if prm.integer else 'a number'}"
                )
            if not prm.lo <= v <= prm.hi:
                raise IndicatorError(f"{name}: {prm.label} must be between {prm.lo} and {prm.hi}")
            values[prm.key] = v
        else:
            values[prm.key] = prm.default
    return ind, values


def compute(spec: str, bars: Bars) -> tuple[Indicator, dict[str, Decimal], dict[str, Series]]:
    ind, params = parse_spec(spec)
    return ind, params, ind.compute(bars, params)
