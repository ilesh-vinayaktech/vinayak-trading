# ruff: noqa: E501
"""The first feature set: price and volume only. Every function maps (sessions, bars) to a value for each session where one is defined.
Rules common to all: a window containing a session with no bar gives NO value; nothing is interpolated; a value inside its warm-up is absent,
never zero; available_at is the latest availability of every input bar used; values are quantised to 12 decimals."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal

from algo.features._shared import Result, SessionBar, latest, q, window


def ret(n: int) -> Callable[[Sequence[date], Mapping[date, SessionBar]], Result]:
    """close[t] / close[t-n] - 1, from n+1 closes."""

    def f(sessions: Sequence[date], bars: Mapping[date, SessionBar]) -> Result:
        out: Result = {}
        for i, d in enumerate(sessions):
            w = window(sessions, i, n + 1, bars)
            if w is not None:
                out[d] = (q(w[-1].close / w[0].close - 1), latest(w))
        return out

    return f


def vol(n: int) -> Callable[[Sequence[date], Mapping[date, SessionBar]], Result]:
    """Sample standard deviation (ddof = 1) of the last n daily simple returns, not annualised; needs n+1 closes."""

    def f(sessions: Sequence[date], bars: Mapping[date, SessionBar]) -> Result:
        out: Result = {}
        for i, d in enumerate(sessions):
            w = window(sessions, i, n + 1, bars)
            if w is None:
                continue
            rets = [w[k].close / w[k - 1].close - 1 for k in range(1, n + 1)]
            mean = sum(rets, Decimal(0)) / n
            var = sum(((r - mean) ** 2 for r in rets), Decimal(0)) / (n - 1)
            out[d] = (q(var.sqrt()), latest(w))
        return out

    return f


def _true_range(cur: SessionBar, prev: SessionBar) -> Decimal:
    return max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close))


def _atr_chain(
    n: int, sessions: Sequence[date], bars: Mapping[date, SessionBar]
) -> dict[date, tuple[Decimal, datetime]]:
    """Wilder's average true range, unquantised, with its availability. The first value is the mean of the first n true ranges (n+1 consecutive
    bars), then ATR[t] = (ATR[t-1] * (n-1) + TR[t]) / n. A missing session breaks the chain: it starts again after the gap."""
    out: dict[date, tuple[Decimal, datetime]] = {}
    run: list[SessionBar] = []  # the consecutive bars since the last gap
    value: Decimal | None = None
    for d in sessions:
        if d not in bars:
            run, value = [], None
            continue
        run.append(bars[d])
        if len(run) == n + 1:
            value = sum((_true_range(run[k], run[k - 1]) for k in range(1, n + 1)), Decimal(0)) / n
        elif len(run) > n + 1:
            assert value is not None
            value = (value * (n - 1) + _true_range(run[-1], run[-2])) / n
        if value is not None:
            out[d] = (value, latest(run))
    return out


def atr(n: int) -> Callable[[Sequence[date], Mapping[date, SessionBar]], Result]:
    """Wilder's average true range, in price units AS OF day t: the adjusted series is rescaled by raw_close[t] / close[t], which undoes any split or
    bonus that takes effect after t (the adjusted series already carries it); on a day with no later action the factor is 1."""

    def f(sessions: Sequence[date], bars: Mapping[date, SessionBar]) -> Result:
        return {
            d: (q(v * bars[d].raw_close / bars[d].close), at)
            for d, (v, at) in _atr_chain(n, sessions, bars).items()
        }

    return f


def atr_pct(n: int) -> Callable[[Sequence[date], Mapping[date, SessionBar]], Result]:
    """atr_n / close[t], as a fraction (the ATR is not rounded before it is divided)."""

    def f(sessions: Sequence[date], bars: Mapping[date, SessionBar]) -> Result:
        return {
            d: (q(v / bars[d].close), at) for d, (v, at) in _atr_chain(n, sessions, bars).items()
        }

    return f


def dist_sma(n: int) -> Callable[[Sequence[date], Mapping[date, SessionBar]], Result]:
    """close[t] / mean(close[t-n+1 .. t]) - 1, from n closes."""

    def f(sessions: Sequence[date], bars: Mapping[date, SessionBar]) -> Result:
        out: Result = {}
        for i, d in enumerate(sessions):
            w = window(sessions, i, n, bars)
            if w is not None:
                mean = sum((b.close for b in w), Decimal(0)) / n
                out[d] = (q(w[-1].close / mean - 1), latest(w))
        return out

    return f


def traded_value(n: int) -> Callable[[Sequence[date], Mapping[date, SessionBar]], Result]:
    """Mean over the last n sessions of raw_close * raw_volume (rupees), from n bars. Unadjusted on purpose: a value actually traded."""

    def f(sessions: Sequence[date], bars: Mapping[date, SessionBar]) -> Result:
        out: Result = {}
        for i, d in enumerate(sessions):
            w = window(sessions, i, n, bars)
            if w is not None:
                out[d] = (
                    q(sum((b.raw_close * b.raw_volume for b in w), Decimal(0)) / n),
                    latest(w),
                )
        return out

    return f
