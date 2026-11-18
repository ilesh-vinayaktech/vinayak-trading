# ruff: noqa: E501
"""The market zone (TODO 6.3): how fearful or greedy the whole market is, and what kind of market it is (bull, bear or sideways; calm or stressed).

Fear/greed is the mean of up to ten signals. Each signal is first reduced to one number a day, then turned into a 0 to 100 score by where
today's number sits against the same number over the previous 45 trading days (its mean and standard deviation, capped at 3 standard deviations either way, so no signal
needs a hand-tuned scale and the average of the eight rarely reaches an extreme). Zones: under 30 extreme fear, 30 to 50 fear, 50 to 70 greed, over 70 extreme greed. 0 is extreme fear, 100 extreme greed:
  momentum         index against its 125-day average
  breadth          share of stocks above their 50-day average
  highs_lows       new 52-week highs against new lows (10-day mean)
  volatility       India VIX against its 50-day average, inverted (a falling VIX is greed)
  advance_decline  advancers against decliners (10-day mean)
  stocks_vs_bonds  20-day return of the index minus that of the government-bond index
  risk_appetite    20-day return of the high-beta index minus the low-volatility index
  size_appetite    20-day return of small caps minus large caps
  gold_demand      10-day return of the index minus that of gold (a gold ETF): gold winning is fear
  fii_positioning  FII open interest in index futures, long less short: net long is greed
A signal with too little history, or whose data is missing, is None and is left out; fewer than four signals gives no score (never a guess).
Point in time: the answer for day `at` uses only days up to `at`, which the tests check by cutting the later days off. These are statistics, not money:
floats are used on purpose. FII/DII flows are not a signal yet: we hold one day of them (TODO 6.3, parked)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

WINDOW = 756  # trading days (3 years) the volatility regime is ranked against
MIN_HISTORY = 60  # fewer prior values than this and the regime volatility is not read
NORM_WINDOW = 45  # each signal against its own previous 45 days (mean and spread)
NORM_MIN = 30  # fewer prior values than this and the signal is not scored
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
    gold: Sequence[float] = field(default_factory=_floats)  # a gold ETF (GOLDBEES)
    fii_net: Sequence[float] = field(
        default_factory=_floats
    )  # FII index-futures open interest, long less short (contracts)
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


CLIP_SD = 3.0  # a signal 3 or more standard deviations from its recent mean scores 0 or 100; in between the score is a straight line


def z_score(history: Sequence[float], value: float) -> float:
    """`value` as a 0 to 100 score from its distance to the history's mean in standard deviations: 50 at the mean, 0 or 100 at 3 sd away, a straight line between
    (so the average of several signals rarely reaches an extreme); a flat history is 50."""
    mean = sum(history) / len(history)
    sd = (sum((h - mean) ** 2 for h in history) / len(history)) ** 0.5
    return 50.0 if sd == 0 else 50.0 + 50.0 * max(-1.0, min(1.0, (value - mean) / sd / CLIP_SD))


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
    "gold_demand": lambda s, i: _diff(
        _ret(s.index, 10, i), _ret(s.gold, 10, i)
    ),  # gold beating stocks over two weeks is fear
    "fii_positioning": lambda s, i: (
        float(s.fii_net[i]) if i < len(s.fii_net) else None
    ),  # FIIs net long index futures is greed
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
        prior = [fn(s, j) for j in range(max(0, i - NORM_WINDOW), i)]
        seen = [v for v in prior if v is not None]
        out[name] = z_score(seen, today) if len(seen) >= NORM_MIN else None
    return out


def _gap(v: float, a: str, b: str, span: str) -> str:
    """ "Stocks 3.2 points ahead of bonds over 20 days" (or behind, when v is negative)."""
    return f"{a} {abs(v) * 100:.1f} points {'ahead of' if v >= 0 else 'behind'} {b} over {span}"


def readings(s: Series, at: int | None = None) -> dict[str, str | None]:
    """The plain-words figure behind each signal for day `at` ("India VIX 14.2, 8% below its 50-day average"), or None when it cannot be worked out.
    The score says how unusual that figure is against its last 45 days; this says what the figure is."""
    i = len(s.index) - 1 if at is None else at
    raw = {name: (fn(s, i) if i >= 0 else None) for name, fn in SIGNALS.items()}
    out: dict[str, str | None] = {name: None for name in SIGNALS}
    if (v := raw["momentum"]) is not None:
        out["momentum"] = f"Index {v * 100:+.1f}% against its 125-day average"
    if (v := raw["breadth"]) is not None:
        out["breadth"] = f"{v:.1f}% of stocks above their 50-day average"
    if (v := raw["highs_lows"]) is not None:
        out["highs_lows"] = f"{v * 100:.0f}% of new 52-week extremes were highs (10-day average)"
    if (v := raw["volatility"]) is not None and i < len(s.vix):
        out["volatility"] = (
            f"India VIX {s.vix[i]:.1f}, {abs(v) * 100:.0f}% {'below' if v >= 0 else 'above'} its 50-day average"
        )
    if (v := raw["advance_decline"]) is not None:
        out["advance_decline"] = f"{v * 100:.0f}% of stocks advancing (10-day average)"
    if (v := raw["stocks_vs_bonds"]) is not None:
        out["stocks_vs_bonds"] = _gap(v, "Stocks", "bonds", "20 days")
    if (v := raw["risk_appetite"]) is not None:
        out["risk_appetite"] = _gap(v, "High-beta", "low-volatility stocks", "20 days")
    if (v := raw["size_appetite"]) is not None:
        out["size_appetite"] = _gap(v, "Small caps", "large caps", "20 days")
    if (v := raw["gold_demand"]) is not None:
        out["gold_demand"] = _gap(v, "Stocks", "gold", "10 days")
    if (v := raw["fii_positioning"]) is not None:
        out["fii_positioning"] = (
            f"FIIs net {'long' if v >= 0 else 'short'} {abs(v):,.0f} index futures contracts"
        )
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
            seen = [v for v in values[max(0, i - NORM_WINDOW) : i] if v is not None]
            day[name] = (
                z_score(seen, today) if today is not None and len(seen) >= NORM_MIN else None
            )
        out.append(day)
    return out


def fear_greed(comps: dict[str, float | None]) -> float | None:
    """The mean of the signals that could be scored, or None with fewer than four."""
    vals = [v for v in comps.values() if v is not None]
    return _mean(vals) if len(vals) >= MIN_SIGNALS else None


def zone_label(score: float) -> str:
    if score < 30:
        return "Extreme fear"
    if score < 50:
        return "Fear"
    if score <= 70:
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
