# ruff: noqa: E501
"""Market context for one stock (the chart's Early Signs panel, redone 2026-11-19 after scripts/study_conditions.py).

What the study found: no feature or combination gave a direction edge that survived testing; only the market regime mattered a little. So this describes WHERE the stock stands
(Nifty regime, sector against the market, the stock against Nifty and its sector, ADX, EMA trend; RSI is `notes.rsi`) and promises nothing about direction. Statistics, not money: floats on purpose.
Pure functions over closes (oldest first); the route does the reading."""

from __future__ import annotations

from collections.abc import Sequence
from statistics import median

IN_LINE = 0.5  # percentage points: a sector within this of the market is "in line"


def _ewm(xs: Sequence[float], alpha: float) -> list[float]:
    out = [xs[0]]
    for x in xs[1:]:
        out.append(alpha * x + (1 - alpha) * out[-1])
    return out


def ret(xs: Sequence[float], n: int) -> float | None:
    """Percent change over the last `n` bars, or None when there is not enough history."""
    if len(xs) <= n or xs[-1 - n] <= 0:
        return None
    return 100 * (xs[-1] / xs[-1 - n] - 1)


def regime(closes: Sequence[float]) -> str | None:
    """Nifty uptrend (close over its 50-day average, that average rising over 10 days and over the 200-day), downtrend (under a falling 50-day average), else sideways. None under 210 closes."""
    n = len(closes)
    if n < 210:
        return None
    s50, s50_before, s200 = (
        sum(closes[n - 50 :]) / 50,
        sum(closes[n - 60 : n - 10]) / 50,
        sum(closes[n - 200 :]) / 200,
    )
    if closes[-1] > s50 and s50 > s50_before and s50 > s200:
        return "uptrend"
    if closes[-1] < s50 and s50 < s50_before:
        return "downtrend"
    return "sideways"


def adx(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], n: int = 14
) -> float | None:
    """Wilder's ADX: how strong the trend is, whichever way it points. None under 3n bars."""
    if len(closes) < 3 * n:
        return None
    tr, pdm, mdm = [], [], []
    for i in range(1, len(closes)):
        tr.append(
            max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        )
        up, dn = highs[i] - highs[i - 1], lows[i - 1] - lows[i]
        pdm.append(up if up > dn and up > 0 else 0.0)
        mdm.append(dn if dn > up and dn > 0 else 0.0)
    a = 1 / n
    atr, p, m = _ewm(tr, a), _ewm(pdm, a), _ewm(mdm, a)
    dx = [
        0.0 if atr[i] == 0 or p[i] + m[i] == 0 else 100 * abs(p[i] - m[i]) / (p[i] + m[i])
        for i in range(len(atr))
    ]
    return _ewm(dx, a)[-1]


def adx_label(v: float | None) -> str | None:
    return (
        None
        if v is None
        else "strong trend"
        if v > 25
        else "no trend"
        if v < 15
        else "moderate trend"
    )


def ema_trend(closes: Sequence[float]) -> str | None:
    """The 20-day exponential average against the 50-day: 'above' or 'below', None under 50 closes."""
    if len(closes) < 50:
        return None
    return "above" if _ewm(closes, 2 / 21)[-1] > _ewm(closes, 2 / 51)[-1] else "below"


def sector_view(
    sector_rets: Sequence[float], market_rets: Sequence[float]
) -> tuple[float, float, str] | None:
    """The sector's median return against the whole market's median over the same window: (sector, market, outperforming | underperforming | in line)."""
    if not sector_rets or not market_rets:
        return None
    s, m = median(sector_rets), median(market_rets)
    return (
        s,
        m,
        "outperforming" if s - m > IN_LINE else "underperforming" if m - s > IN_LINE else "in line",
    )


def breakout_facts(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]
) -> dict[str, float | bool | str | None]:
    """Plain facts about the latest COMPLETED daily candle against its own recent history; nothing here says what happens next. Every reference level excludes the candle being judged.
    above_20d_high: the close is over the highest high of the 20 candles before it. breakout: 'crossed today' (the previous close was not over its own prior 20-day high), 'already above', or 'none'.
    new_52w_high: the close is over the highest high of up to the 252 candles before it, with at least 200 of them. extension_atr: (close - EMA20) / ATR14, signed. Each is None when its history is missing."""
    n = len(closes)
    out: dict[str, float | bool | str | None] = {
        "above_20d_high": None,
        "high_20d": None,
        "breakout": None,
        "new_52w_high": None,
        "high_52w": None,
        "extension_atr": None,
    }
    if n >= 21:
        h20 = max(highs[n - 21 : n - 1])
        out.update(above_20d_high=closes[-1] > h20, high_20d=h20)
        was_above = closes[-2] > max(highs[n - 22 : n - 2]) if n >= 22 else None
        if was_above is not None:
            out["breakout"] = (
                "none" if closes[-1] <= h20 else "already above" if was_above else "crossed today"
            )
    if n >= 201:
        h52 = max(highs[max(0, n - 253) : n - 1])
        out.update(new_52w_high=closes[-1] > h52, high_52w=h52)
    if n >= 30:
        tr = [
            max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            for i in range(1, n)
        ]
        a = _ewm(tr, 1 / 14)[-1]
        if a > 0:
            out["extension_atr"] = (closes[-1] - _ewm(closes, 2 / 21)[-1]) / a
    return out
