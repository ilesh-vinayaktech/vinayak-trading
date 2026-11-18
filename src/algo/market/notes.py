# ruff: noqa: E501
"""What is worth noticing about one stock right now, as short plain facts (TODO 6.8 follow-up): a breakout or breakdown, a stock testing resistance (about to break), an inside bar or
the narrowest range in a week (coiling), a volume or delivery surge, a gap, a new 52-week high or low, an overbought or oversold RSI, a fresh golden or death cross.

Pure: it takes the stock's finished daily bars (oldest first) and, while the market is open, today's live day (`LiveDay`), and returns notes ranked by how much they matter (rank 1
first). The context that does not come from prices (news, corporate actions, deals, insider trades) is added by the caller with the same `Note`. These are facts about the chart, not
signals: none of them has been shown to predict returns, and the portal says so beside them. Statistics, not money: floats on purpose."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from algo.market import levels

GAP_PCT = 2.0  # the open against yesterday's close
BIG_MOVE_PCT = 4.0  # today's move so far
NEAR_EXTREME = 0.02  # within this of the 52-week high or low
VOLUME_SURGE = 2.0  # times the 20-day average
DELIVERY_SURGE = 1.5  # times its own 20-day norm
OVERBOUGHT, OVERSOLD = 70.0, 30.0
CROSS_DAYS = 5  # a golden or death cross counts for this many sessions
MIN_FOR_EXTREMES = 200  # bars needed before a 52-week high or low means something
MIN_YEAR_RANGE = 0.10  # and the year's high must be this far above its low: a stock that has not moved has no extremes

RANK_BREAK, RANK_NEAR, RANK_CONTEXT, RANK_PATTERN, RANK_BACKDROP = 1, 2, 3, 4, 5


@dataclass(frozen=True)
class Note:
    kind: str  # a stable key the page can style or filter on
    tone: str  # good | bad | warn | info
    text: str  # short, for a chip
    rank: int  # 1 matters most
    detail: str | None = None  # the longer reading, for a tooltip


@dataclass(frozen=True)
class LiveDay:
    """Today's session so far, from the live quote."""

    open: float | None
    high: float
    low: float
    price: float
    volume: float


def rsi(close: Sequence[float], period: int = 14) -> float | None:
    """Wilder's RSI of the last close; None with too few closes."""
    if len(close) <= period:
        return None
    d = np.diff(np.asarray(close, dtype=float))
    gain, loss = np.clip(d, 0, None), np.clip(-d, 0, None)
    ag, al = gain[:period].mean(), loss[:period].mean()
    for g, lo in zip(gain[period:], loss[period:], strict=True):
        ag, al = (ag * (period - 1) + g) / period, (al * (period - 1) + lo) / period
    if al == 0:
        return 100.0 if ag > 0 else 50.0
    return float(100.0 - 100.0 / (1.0 + ag / al))


def _cross(close: Sequence[float]) -> tuple[str, int] | None:
    """('golden' | 'death', sessions ago) when the 50-day average crossed the 200-day average in the last CROSS_DAYS sessions."""
    n = len(close)
    if n < 200 + CROSS_DAYS:
        return None
    c = np.asarray(close, dtype=float)
    cs = np.concatenate([[0.0], np.cumsum(c)])

    def sma(k: int, end: int) -> float:  # average of the k closes ending at index `end` (inclusive)
        return float((cs[end + 1] - cs[end + 1 - k]) / k)

    for ago in range(CROSS_DAYS):
        i = n - 1 - ago
        before, after = sma(50, i - 1) - sma(200, i - 1), sma(50, i) - sma(200, i)
        if before <= 0 < after:
            return "golden", ago
        if before >= 0 > after:
            return "death", ago
    return None


def _when(ago: int) -> str:
    return "today" if ago == 0 else "yesterday" if ago == 1 else f"{ago} sessions ago"


def price_notes(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    volume: Sequence[float],
    delivery_pct: Sequence[float | None],
    live: LiveDay | None = None,
) -> list[Note]:
    """The notes the finished bars (and today's live day, if any) support, most important first. Fewer than two bars gives none."""
    n = len(close)
    if n < 2 or not (n == len(high) == len(low) == len(volume) == len(delivery_pct)):
        return []
    out: list[Note] = []
    price = live.price if live else close[-1]
    prev = close[-1]
    h, lo, c, v = list(high), list(low), list(close), list(volume)
    if live:  # today as the last bar, so a break today is seen today (its volume is only what has traded so far)
        h.append(live.high)
        lo.append(live.low)
        c.append(live.price)
        v.append(live.volume)
    norm = [p for p in delivery_pct[-21:-1] if p is not None]
    deliv_vs = (
        delivery_pct[-1] / (sum(norm) / len(norm))
        if not live and delivery_pct[-1] is not None and norm and sum(norm) > 0
        else None
    )
    found = levels.analyse(h, lo, c, v, deliv_vs)
    if found:
        st = found["status"]
        assert isinstance(st, dict)
        state = str(st["state"])
        lvl = st.get("level")
        at = f" at {lvl:,.2f}" if isinstance(lvl, float) else ""
        if state == "Breakout":
            out.append(
                Note(
                    "breakout",
                    "good",
                    "Breakout",
                    RANK_BREAK,
                    f"Closed above resistance{at} on strong volume and delivery",
                )
            )
        elif state == "Breakout, weak volume":
            out.append(
                Note(
                    "breakout_weak",
                    "warn",
                    "Breakout, weak volume",
                    RANK_BREAK,
                    f"Above resistance{at}, but volume or delivery did not confirm it",
                )
            )
        elif state == "Breakdown":
            out.append(
                Note(
                    "breakdown",
                    "bad",
                    "Breakdown",
                    RANK_BREAK,
                    f"Closed below support{at} on strong volume and delivery",
                )
            )
        elif state == "Breakdown, weak volume":
            out.append(
                Note(
                    "breakdown_weak",
                    "warn",
                    "Breakdown, weak volume",
                    RANK_BREAK,
                    f"Below support{at}, but volume or delivery did not confirm it",
                )
            )
        elif state == "Testing resistance":
            out.append(
                Note(
                    "near_breakout",
                    "info",
                    "Near breakout",
                    RANK_NEAR,
                    f"Just under resistance{at}: a close above it would be a breakout",
                )
            )
        elif state == "Testing support":
            out.append(
                Note(
                    "near_support",
                    "info",
                    "At support",
                    RANK_NEAR,
                    f"Sitting on support{at}: a close below it would be a breakdown",
                )
            )
        sup, res = found.get("supports"), found.get("resistances")
        if (
            isinstance(sup, list)
            and isinstance(res, list)
            and sup
            and res
            and state in ("Inside its range",)
        ):
            out.append(
                Note(
                    "range",
                    "info",
                    f"Between {sup[0]['price']:,.0f} and {res[0]['price']:,.0f}",
                    RANK_BACKDROP,
                    f"Support {sup[0]['price']:,.2f} ({sup[0]['distance_pct']:+.1f}%), resistance {res[0]['price']:,.2f} ({res[0]['distance_pct']:+.1f}%)",
                )
            )
    if live and live.open and prev > 0:
        gap = (live.open / prev - 1) * 100
        if gap >= GAP_PCT:
            out.append(
                Note(
                    "gap_up",
                    "good",
                    f"Gapped up {gap:.1f}%",
                    RANK_NEAR,
                    f"Opened {gap:.1f}% above yesterday's close",
                )
            )
        elif gap <= -GAP_PCT:
            out.append(
                Note(
                    "gap_down",
                    "bad",
                    f"Gapped down {abs(gap):.1f}%",
                    RANK_NEAR,
                    f"Opened {abs(gap):.1f}% below yesterday's close",
                )
            )
    if live and prev > 0:
        move = (price / prev - 1) * 100
        if move >= BIG_MOVE_PCT:
            out.append(Note("big_up", "good", f"Up {move:.1f}% today", RANK_NEAR))
        elif move <= -BIG_MOVE_PCT:
            out.append(Note("big_down", "bad", f"Down {abs(move):.1f}% today", RANK_NEAR))
    top, bottom = (max(high[-252:]), min(low[-252:])) if n >= MIN_FOR_EXTREMES else (0.0, 0.0)
    if n >= MIN_FOR_EXTREMES and bottom > 0 and top / bottom - 1 >= MIN_YEAR_RANGE:
        if price > top:
            out.append(
                Note(
                    "new_high",
                    "good",
                    "New 52-week high",
                    RANK_BREAK,
                    f"Above the previous 52-week high of {top:,.2f}",
                )
            )
        elif price >= top * (1 - NEAR_EXTREME):
            out.append(
                Note(
                    "near_high",
                    "good",
                    "Near 52-week high",
                    RANK_NEAR,
                    f"Within {100 * (1 - price / top):.1f}% of its 52-week high of {top:,.2f}",
                )
            )
        if price < bottom:
            out.append(
                Note(
                    "new_low",
                    "bad",
                    "New 52-week low",
                    RANK_BREAK,
                    f"Below the previous 52-week low of {bottom:,.2f}",
                )
            )
        elif price <= bottom * (1 + NEAR_EXTREME):
            out.append(
                Note(
                    "near_low",
                    "bad",
                    "Near 52-week low",
                    RANK_NEAR,
                    f"Within {100 * (price / bottom - 1):.1f}% of its 52-week low of {bottom:,.2f}",
                )
            )
    if high[-1] < high[-2] and low[-1] > low[-2]:
        out.append(
            Note(
                "inside_bar",
                "info",
                "Inside bar",
                RANK_PATTERN,
                "Last session's range sat inside the one before it: the stock is coiling, and a move out of that range is the signal",
            )
        )
    if (
        n >= 7
        and high[-1] > low[-1]
        and (high[-1] - low[-1]) <= min(h_ - l_ for h_, l_ in zip(high[-7:], low[-7:], strict=True))
    ):
        out.append(
            Note(
                "nr7",
                "info",
                "Narrowest range in 7 days",
                RANK_PATTERN,
                "The tightest session of the last seven (NR7): volatility is compressed, and often expands after",
            )
        )
    if n > 21:
        avg = float(np.mean(volume[-21:-1]))
        if avg > 0 and volume[-1] >= VOLUME_SURGE * avg:
            up = close[-1] >= close[-2]
            out.append(
                Note(
                    "volume_surge",
                    "good" if up else "bad",
                    f"Volume {volume[-1] / avg:.1f}x average",
                    RANK_PATTERN,
                    f"Last session traded {volume[-1] / avg:.1f}x its 20-day average volume, with the price {'up' if up else 'down'}",
                )
            )
    last_deliv = delivery_pct[-1]
    if (
        last_deliv is not None
        and norm
        and sum(norm) > 0
        and last_deliv / (sum(norm) / len(norm)) >= DELIVERY_SURGE
    ):
        ratio = last_deliv / (sum(norm) / len(norm))
        out.append(
            Note(
                "delivery_surge",
                "good",
                f"Delivery {ratio:.1f}x norm",
                RANK_PATTERN,
                f"{last_deliv:.0f}% of last session's shares were taken for delivery, {ratio:.1f}x its own 20-day norm: buyers are keeping them, not trading them",
            )
        )
    r = rsi(c)
    if r is not None and r >= OVERBOUGHT:
        out.append(
            Note(
                "overbought",
                "warn",
                f"Overbought (RSI {r:.0f})",
                RANK_BACKDROP,
                "RSI above 70: it has run hard; this alone is not a sell signal",
            )
        )
    elif r is not None and r <= OVERSOLD:
        out.append(
            Note(
                "oversold",
                "warn",
                f"Oversold (RSI {r:.0f})",
                RANK_BACKDROP,
                "RSI below 30: it has fallen hard; this alone is not a buy signal",
            )
        )
    cross = _cross(close)
    if cross:
        kind, ago = cross
        out.append(
            Note(
                f"{kind}_cross",
                "good" if kind == "golden" else "bad",
                f"{'Golden' if kind == 'golden' else 'Death'} cross",
                RANK_PATTERN,
                f"The 50-day average crossed {'above' if kind == 'golden' else 'below'} the 200-day average {_when(ago)}",
            )
        )
    if len(c) >= 200 and price < float(np.mean(c[-200:])):
        out.append(
            Note(
                "below_200",
                "bad",
                "Below 200-day average",
                RANK_BACKDROP,
                "Trading under its 200-day average: the long trend is down",
            )
        )
    return sorted(out, key=lambda x: x.rank)
