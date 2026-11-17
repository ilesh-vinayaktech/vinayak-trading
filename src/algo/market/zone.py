# ruff: noqa: E501
"""The market zone (TODO 6.3): how fearful or greedy the whole market is, and what kind of market it is (bull, bear or sideways; calm or stressed).

Fear/greed is the mean of up to eight INDEPENDENT signals. Each signal is first reduced to one number a day, then turned into a 0 to 100 score by where
today's number sits among the same number over the previous 756 trading days (3 years) (a percentile, so no signal needs a hand-tuned scale and each is read
against the market's own recent history). 0 is extreme fear, 100 extreme greed:
  momentum         index against its 125-day average
  breadth          share of stocks above their 50-day average
  highs_lows       new 52-week highs against new lows (10-day mean)
  volatility       India VIX against its 50-day average, inverted (a falling VIX is greed)
  advance_decline  advancers against decliners (10-day mean)
  stocks_vs_bonds  20-day return of the index minus that of the government-bond index
  risk_appetite    20-day return of the high-beta index minus the low-volatility index
  size_appetite    20-day return of small caps minus large caps
A signal with too little history, or whose data is missing, is None and is left out; fewer than four signals gives no score (never a guess).
Point in time: the answer for day `at` uses only days up to `at`, which the tests check by cutting the later days off. These are statistics, not money:
floats are used on purpose. FII/DII flows are not a signal yet: we hold one day of them (TODO 6.3, parked)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

WINDOW = 756  # trading days (3 years) a signal is ranked against: long enough that a lasting bull market keeps reading as greed
MIN_HISTORY = 60  # fewer prior values than this and the signal is not scored
MIN_SIGNALS = 4  # fewer signals than this and there is no composite


def _floats() -> list[float]:
    return []


def _ints() -> list[int]:
    return []


@dataclass(frozen=True)
class Series:
    """Aligned daily inputs, oldest first, one value per trading day. A series that is empty or shorter than the others is simply unavailable."""

    index: Sequence[float] = field(default_factory=_floats)  # a broad index (Nifty 500)
    vix: Sequence[float] = field(default_factory=_floats)
    bond: Sequence[float] = field(default_factory=_floats)  # government-bond index
    high_beta: Sequence[float] = field(default_factory=_floats)
    low_vol: Sequence[float] = field(default_factory=_floats)
    small: Sequence[float] = field(default_factory=_floats)
    large: Sequence[float] = field(default_factory=_floats)
    pct_above_50: Sequence[float] = field(
        default_factory=_floats
    )  # % of stocks above their 50-day average
    pct_above_200: Sequence[float] = field(default_factory=_floats)
    highs: Sequence[int] = field(default_factory=_ints)  # stocks at a new 52-week high
    lows: Sequence[int] = field(default_factory=_ints)
    advancers: Sequence[int] = field(default_factory=_ints)
    decliners: Sequence[int] = field(default_factory=_ints)


def pct_rank(history: Sequence[float], value: float) -> float:
    """Where `value` sits among `history`, 0 to 100; values equal to it count half, so a value alone in a flat history is 50."""
    if not history:
        return 50.0
    below = sum(1 for h in history if h < value)
    equal = sum(1 for h in history if h == value)
    return 100.0 * (below + 0.5 * equal) / len(history)


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def _sma(xs: Sequence[float], n: int, i: int) -> float | None:
    return _mean(xs[i - n + 1 : i + 1]) if i + 1 >= n and i < len(xs) else None


def _ret(xs: Sequence[float], n: int, i: int) -> float | None:
    if i >= len(xs) or i < n or xs[i - n] == 0:
        return None
    return xs[i] / xs[i - n] - 1


def _share(up: Sequence[int], down: Sequence[int], i: int, n: int = 10) -> float | None:
    """Mean of up/(up+down) over the last n days (0.5 on a day with neither)."""
    if i + 1 < n or i >= len(up) or i >= len(down):
        return None
    shares = [
        (up[j] / (up[j] + down[j])) if (up[j] + down[j]) else 0.5 for j in range(i - n + 1, i + 1)
    ]
    return _mean(shares)


def _diff(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


def _momentum(s: Series, i: int) -> float | None:
    avg = _sma(s.index, 125, i)
    return None if avg is None or avg == 0 else s.index[i] / avg - 1


def _volatility(s: Series, i: int) -> float | None:
    avg = _sma(s.vix, 50, i)
    return None if avg is None or avg == 0 else -(s.vix[i] / avg - 1)  # a high VIX is fear


SIGNALS: dict[str, Callable[[Series, int], float | None]] = {
    "momentum": _momentum,
    "breadth": lambda s, i: float(s.pct_above_50[i]) if i < len(s.pct_above_50) else None,
    "highs_lows": lambda s, i: _share(s.highs, s.lows, i),
    "volatility": _volatility,
    "advance_decline": lambda s, i: _share(s.advancers, s.decliners, i),
    "stocks_vs_bonds": lambda s, i: _diff(_ret(s.index, 20, i), _ret(s.bond, 20, i)),
    "risk_appetite": lambda s, i: _diff(_ret(s.high_beta, 20, i), _ret(s.low_vol, 20, i)),
    "size_appetite": lambda s, i: _diff(_ret(s.small, 20, i), _ret(s.large, 20, i)),
}


def components(s: Series, at: int | None = None) -> dict[str, float | None]:
    """Each signal as a 0 to 100 score for day `at` (default the last day), or None when it cannot be scored."""
    i = len(s.index) - 1 if at is None else at
    out: dict[str, float | None] = {}
    for name, fn in SIGNALS.items():
        today = fn(s, i) if i >= 0 else None
        if today is None:
            out[name] = None
            continue
        prior = [fn(s, j) for j in range(max(0, i - WINDOW), i)]
        seen = [v for v in prior if v is not None]
        out[name] = pct_rank(seen, today) if len(seen) >= MIN_HISTORY else None
    return out


def score_all(s: Series) -> list[dict[str, float | None]]:
    """`components` for every day at once (each signal computed once, then ranked per day): the same answers, fast enough to backfill years."""
    n = len(s.index)
    raw = {name: [fn(s, i) for i in range(n)] for name, fn in SIGNALS.items()}
    out: list[dict[str, float | None]] = []
    for i in range(n):
        day: dict[str, float | None] = {}
        for name, values in raw.items():
            today = values[i]
            seen = [v for v in values[max(0, i - WINDOW) : i] if v is not None]
            day[name] = (
                pct_rank(seen, today) if today is not None and len(seen) >= MIN_HISTORY else None
            )
        out.append(day)
    return out


def fear_greed(comps: dict[str, float | None]) -> float | None:
    """The mean of the signals that could be scored, or None with fewer than four."""
    vals = [v for v in comps.values() if v is not None]
    return _mean(vals) if len(vals) >= MIN_SIGNALS else None


def zone_label(score: float) -> str:
    if score < 25:
        return "Extreme fear"
    if score < 45:
        return "Fear"
    if score <= 55:
        return "Neutral"
    if score <= 75:
        return "Greed"
    return "Extreme greed"


@dataclass(frozen=True)
class Regime:
    trend: str  # BULL | BEAR | SIDEWAYS | UNKNOWN
    volatility: str  # CALM | NORMAL | STRESSED | UNKNOWN


def regime(s: Series, at: int | None = None) -> Regime:
    """Trend: BULL when the index is above its 200-day average, the 50-day is above the 200-day and most stocks are above their own 200-day
    (BEAR is the mirror image, anything else is SIDEWAYS). Volatility: STRESSED when India VIX is in the top fifth of its year or at least 25,
    CALM in the bottom 30%."""
    i = len(s.index) - 1 if at is None else at
    trend = "UNKNOWN"
    if 199 <= i < len(s.index):
        close, sma200, sma50 = s.index[i], _sma(s.index, 200, i), _sma(s.index, 50, i)
        assert sma200 is not None and sma50 is not None
        wide = s.pct_above_200[i] if i < len(s.pct_above_200) else None
        if close > sma200 and sma50 > sma200 and (wide is None or wide >= 50):
            trend = "BULL"
        elif close < sma200 and sma50 < sma200 and (wide is None or wide < 50):
            trend = "BEAR"
        else:
            trend = "SIDEWAYS"
    vol = "UNKNOWN"
    if i < len(s.vix):
        prior = list(s.vix[max(0, i - WINDOW) : i])
        if len(prior) >= MIN_HISTORY:
            rank = pct_rank(prior, s.vix[i])
            vol = "STRESSED" if rank >= 80 or s.vix[i] >= 25 else "CALM" if rank <= 30 else "NORMAL"
    return Regime(trend, vol)
