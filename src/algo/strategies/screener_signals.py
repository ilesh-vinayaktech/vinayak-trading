# ruff: noqa: E501
"""One stock's buy/sell decisions under a screener strategy (decisions only, no P&L).

The strategy (algo.strategies.screener) runs the screen after every session: a stock that matches is in the buy zone, one
that stops matching is sold. So on a chart a stock is a BUY the day it starts matching and a SELL the day it stops, read from
that stock's own bars alone (nothing is looked up for other stocks). What this leaves out, because it concerns the whole
portfolio: the limit on how many stocks are held at once and the ranking among stocks that match on the same day. A BUY here
is therefore the screen's signal for this stock, not a promise the full strategy would have bought it (the same caveat as the
trend-pullback signals). UNVALIDATED research: it shows how the rules read a chart, not that they make money."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from algo.data.reader import IST, AdjBar
from algo.strategies.fundamentals import FundamentalsBook
from algo.strategies.scorebook import ScoreBook
from algo.strategies.screener import ScreenSpec, still_matches
from algo.strategies.signals import SignalDay

LOOKBACK_BARS = 260  # sessions: the longest technical (1-year change) reads 253 closes


def _day(b: AdjBar) -> date:
    return b.ts.astimezone(IST).date()


def replay(
    bars: Sequence[AdjBar],
    start: date,
    end: date,
    spec: ScreenSpec,
    book: FundamentalsBook | None = None,
    iid: int | None = None,
    scores: ScoreBook | None = None,
) -> list[SignalDay]:
    """The decision on each session from `start` to `end` (`bars` should reach back a year before `start`, for the indicators).
    Whether the stock was already in the buy zone just before `start` is read from the bars before it. A decision is made after
    the day's close and filled at the next session's open (None on the last bar)."""
    held = False
    out: list[SignalDay] = []
    for i, b in enumerate(bars):
        day = _day(b)
        if day > end:
            break
        now = still_matches(spec, bars[max(0, i + 1 - LOOKBACK_BARS) : i + 1], book, iid, scores)
        if day >= start:
            action = reason = None
            if now and not held:
                action, reason = "BUY", "matches the screen"
            elif held and not now:
                action, reason = "SELL", "no longer matches the screen"
            nxt = bars[i + 1] if action and i + 1 < len(bars) else None
            out.append(
                SignalDay(
                    day, b.close, None, None, True, action, reason, now,
                    _day(nxt) if nxt else None, nxt.open if nxt else None,
                )
            )  # fmt: skip
        held = now
    return out
