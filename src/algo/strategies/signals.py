# ruff: noqa: E501
"""One stock's buy/sell decisions for the trend-pullback strategy over a date range (decisions only, no P&L).

Uses the strategy's own indicator rule (close, SMA, RSI) and its stateless entry/exit tests, applied to a single stock's adjusted
daily bars, walking day by day with a held / not-held flag. `holding` says whether the replay starts already holding the stock.
What this deliberately leaves out, because it concerns the whole portfolio and not one stock: the limit on how many stocks are
held at once, the choice among several stocks that are oversold on the same day, and index membership. So a BUY here is the
strategy's signal for this stock, not a promise that the full strategy would have bought it. A decision is made after the day's
close and filled at the next session's open (the fill is None on the last bar: there is no next session yet).
UNVALIDATED research: it shows how the rules read a chart, not that they make money."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from algo.data.reader import IST, AdjBar
from algo.indicators import catalog, core
from algo.strategies.trend_pullback import RSI_LEN, WARMUP, TrendPullbackParams


@dataclass(frozen=True)
class SignalDay:
    day: date
    close: Decimal
    sma: Decimal | None
    rsi: Decimal | None
    ready: bool  # enough history for both indicators
    action: str | None  # "BUY" or "SELL", decided after this day's close
    reason: str | None
    holding_after: bool
    fill_day: date | None
    fill_price: Decimal | None


def replay(
    bars: Sequence[AdjBar], p: TrendPullbackParams, start: date, end: date, *, holding: bool = False
) -> list[SignalDay]:
    """The decision on each session from `start` to `end` inclusive. Bars before `start` are history for the indicators."""
    series = catalog.Bars(
        [b.open for b in bars], [b.high for b in bars], [b.low for b in bars],
        [b.close for b in bars], [b.volume for b in bars],
    )  # fmt: skip
    sma = core.sma(series.close, p.trend_sma)
    rsi = catalog.compute(f"rsi:{RSI_LEN}", series)[2]["value"]
    held, out = holding, []
    for i, b in enumerate(bars):
        day = b.ts.astimezone(IST).date()
        if day > end:
            break
        if day < start:
            continue  # earlier days are only history for the indicators; the holding state begins at `start`
        enough = i + 1 >= p.trend_sma + WARMUP and sma[i] is not None and rsi[i] is not None
        s, r = (sma[i], rsi[i]) if enough else (None, None)
        action = reason = None
        if s is not None and r is not None:
            if held:
                if not b.close > s:
                    action, reason = "SELL", "below_trend"
                elif r > p.exit_rsi:
                    action, reason = "SELL", "rsi_above_exit"
            elif b.close > s and r < p.entry_rsi:
                action, reason = "BUY", "oversold in an uptrend"
            held = held if action is None else action == "BUY"
        nxt = bars[i + 1] if action and i + 1 < len(bars) else None
        out.append(
            SignalDay(
                day, b.close, s, r, s is not None, action, reason, held,
                nxt.ts.astimezone(IST).date() if nxt else None, nxt.open if nxt else None,
            )
        )  # fmt: skip
    return out
