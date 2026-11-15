# ruff: noqa: E501
"""The second feature set: price and volume only, version 1, in its OWN module so that adding it does not change the hash (and so the version) of the first twelve, whose
manifest covers price.py. Same rules as price.py: a window containing a session with no bar gives NO value; nothing is interpolated; a value inside its warm-up is absent,
never zero; available_at is the latest availability of every input bar; values are quantised to 12 decimals."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from decimal import Decimal

from algo.features._shared import Result, SessionBar, latest, q, window

LN2 = Decimal(2).ln()


def rsi(n: int) -> Callable[[Sequence[date], Mapping[date, SessionBar]], Result]:
    """Wilder's relative strength index, 0 to 100. The first value uses the plain mean of the first n gains and the first n losses (n+1 consecutive closes), then
    avg[t] = (avg[t-1] * (n-1) + change[t]) / n for gains and losses separately. Only rises give 100, only falls give 0, no movement at all gives 50. A missing session breaks
    the chain: it starts again after the gap."""

    def f(sessions: Sequence[date], bars: Mapping[date, SessionBar]) -> Result:
        out: Result = {}
        run: list[SessionBar] = []
        gain = loss = None
        for d in sessions:
            if d not in bars:
                run, gain, loss = [], None, None
                continue
            run.append(bars[d])
            if len(run) == n + 1:
                changes = [run[k].close - run[k - 1].close for k in range(1, n + 1)]
                gain = sum((c for c in changes if c > 0), Decimal(0)) / n
                loss = sum((-c for c in changes if c < 0), Decimal(0)) / n
            elif len(run) > n + 1:
                assert gain is not None and loss is not None
                change = run[-1].close - run[-2].close
                gain = (gain * (n - 1) + max(change, Decimal(0))) / n
                loss = (loss * (n - 1) + max(-change, Decimal(0))) / n
            if gain is not None and loss is not None:
                value = (
                    (Decimal(100) if gain > 0 else Decimal(50))
                    if loss == 0
                    else Decimal(100) - Decimal(100) / (1 + gain / loss)
                )
                out[d] = (q(value), latest(run))
        return out

    return f


def dist_high(n: int) -> Callable[[Sequence[date], Mapping[date, SessionBar]], Result]:
    """close[t] / max(close[t-n+1 .. t]) - 1: how far below its n-session high the close is. Never positive."""

    def f(sessions: Sequence[date], bars: Mapping[date, SessionBar]) -> Result:
        out: Result = {}
        for i, d in enumerate(sessions):
            w = window(sessions, i, n, bars)
            if w is not None:
                out[d] = (q(w[-1].close / max(b.close for b in w) - 1), latest(w))
        return out

    return f


def dist_low(n: int) -> Callable[[Sequence[date], Mapping[date, SessionBar]], Result]:
    """close[t] / min(close[t-n+1 .. t]) - 1: how far above its n-session low the close is. Never negative."""

    def f(sessions: Sequence[date], bars: Mapping[date, SessionBar]) -> Result:
        out: Result = {}
        for i, d in enumerate(sessions):
            w = window(sessions, i, n, bars)
            if w is not None:
                out[d] = (q(w[-1].close / min(b.close for b in w) - 1), latest(w))
        return out

    return f


def volume_ratio(
    short: int, long: int
) -> Callable[[Sequence[date], Mapping[date, SessionBar]], Result]:
    """mean(raw_volume over the last `short` sessions) / mean(raw_volume over the last `long` sessions), from `long` bars. No value when the long window traded nothing."""

    def f(sessions: Sequence[date], bars: Mapping[date, SessionBar]) -> Result:
        out: Result = {}
        for i, d in enumerate(sessions):
            w = window(sessions, i, long, bars)
            if w is None:
                continue
            long_mean = sum((b.raw_volume for b in w), Decimal(0)) / long
            if long_mean == 0:
                continue
            short_mean = sum((b.raw_volume for b in w[-short:]), Decimal(0)) / short
            out[d] = (q(short_mean / long_mean), latest(w))
        return out

    return f


def range_vol(n: int) -> Callable[[Sequence[date], Mapping[date, SessionBar]], Result]:
    """Parkinson's range volatility over the last n sessions: sqrt(mean(ln(high/low)^2) / (4 ln 2)), a fraction per day, not annualised. Uses the adjusted high and low (only their
    ratio matters). No value when any session in the window has a non-positive low or a high below its low."""

    def f(sessions: Sequence[date], bars: Mapping[date, SessionBar]) -> Result:
        out: Result = {}
        for i, d in enumerate(sessions):
            w = window(sessions, i, n, bars)
            if w is None or any(b.low <= 0 or b.high < b.low for b in w):
                continue
            mean_sq = sum(((b.high / b.low).ln() ** 2 for b in w), Decimal(0)) / n
            out[d] = (q((mean_sq / (4 * LN2)).sqrt()), latest(w))
        return out

    return f


def max_drawdown(n: int) -> Callable[[Sequence[date], Mapping[date, SessionBar]], Result]:
    """The deepest fall from a running peak among the last n closes, as a fraction (0 or negative): min over the window of close / running-high - 1."""

    def f(sessions: Sequence[date], bars: Mapping[date, SessionBar]) -> Result:
        out: Result = {}
        for i, d in enumerate(sessions):
            w = window(sessions, i, n, bars)
            if w is None:
                continue
            peak, worst = w[0].close, Decimal(0)
            for b in w:
                peak = max(peak, b.close)
                worst = min(worst, b.close / peak - 1)
            out[d] = (q(worst), latest(w))
        return out

    return f
