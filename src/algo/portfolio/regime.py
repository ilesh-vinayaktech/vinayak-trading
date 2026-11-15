# ruff: noqa: E501
"""Market regime from a benchmark's closing prices (plan.md section 10): a trend label and a volatility label, from fixed written rules.

Callers: tests/unit/portfolio/test_regime.py; no production caller yet. User's instruction: "do as much as you can do yourself, keep taking things one by one from
@TODO.md and @plan.md ... keep things finishing with test". Pure: a list of closes in date order (oldest first), the last one being 'today'. No lookahead is
possible by construction: only the closes given are read.
Trend (close C, 50-day average S50, 200-day average S200):
  SIDEWAYS     C within 2% of S200 and S50 within 1% of S200
  STRONG_BULL  C > S50 > S200            WEAK_BULL  C > S200 otherwise
  STRONG_BEAR  C < S50 < S200            WEAK_BEAR  C < S200 otherwise
Volatility: the 20-day standard deviation of daily returns, ranked against the same measure on every earlier day of the last 252: HIGH at the 80th percentile or
above, LOW at the 20th or below, else NORMAL. Fewer than 252 + 20 closes (or 200 for trend) and the regime is UNKNOWN, never a guess."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

VOL_WINDOW = 20
VOL_HISTORY = 252
HIGH_PCT = 0.80
LOW_PCT = 0.20


@dataclass(frozen=True)
class Regime:
    trend: str
    volatility: str
    detail: dict[str, float]


def _sma(x: Sequence[float], n: int) -> float:
    return sum(x[-n:]) / n


def _vol(closes: Sequence[float]) -> float:
    r = [b / a - 1 for a, b in zip(closes, closes[1:], strict=False)]
    m = sum(r) / len(r)
    return math.sqrt(sum((v - m) ** 2 for v in r) / (len(r) - 1))


def classify(closes: Sequence[float]) -> Regime:
    if any(c <= 0 or not math.isfinite(c) for c in closes):
        raise ValueError("closes must be positive numbers")
    trend, vol = "UNKNOWN", "UNKNOWN"
    detail: dict[str, float] = {}
    if len(closes) >= 200:
        c, s50, s200 = closes[-1], _sma(closes, 50), _sma(closes, 200)
        detail.update(close=c, sma50=s50, sma200=s200)
        if abs(c / s200 - 1) < 0.02 and abs(s50 / s200 - 1) < 0.01:
            trend = "SIDEWAYS"
        elif c > s200:
            trend = "STRONG_BULL" if c > s50 > s200 else "WEAK_BULL"
        else:
            trend = "STRONG_BEAR" if c < s50 < s200 else "WEAK_BEAR"
    need = VOL_HISTORY + VOL_WINDOW
    if len(closes) >= need:
        series = [
            _vol(closes[i - VOL_WINDOW : i + 1])
            for i in range(len(closes) - VOL_HISTORY, len(closes))
        ]
        today, earlier = series[-1], series[:-1]
        if max(series) == min(
            series
        ):  # a market that never moved has no volatility regime to speak of
            return Regime(trend, "NORMAL", detail | {"vol_20d": today, "vol_percentile": 0.5})
        pct = sum(1 for v in earlier if v <= today) / len(earlier)
        detail.update(vol_20d=today, vol_percentile=pct)
        vol = "HIGH" if pct >= HIGH_PCT else "LOW" if pct <= LOW_PCT else "NORMAL"
    return Regime(trend, vol, detail)
