"""Nifty 200 trend-filtered 12-1 momentum (long-only, monthly) and its plain-momentum baseline.

Pure decision logic: membership arrives as plain interval data and prices only through Context, so
the strategy holds no database, broker or clock. Rules (fixed, versioned with `version`):
  * universe: point-in-time members on the decision day (start inclusive, end exclusive)
  * score: P[t-21] / P[t-L] - 1 on split/bonus-adjusted closes, t = the latest bar
  * a member is READY only with a bar on each of the last 253 market sessions (a session is a day
    on which at least half of the members have a bar) and positive closes. Others are INSUFFICIENT_
    HISTORY (listed later) or DATA_GAP; both are reported, never silently dropped.
  * breadth = READY members above their own SMA(200) / READY members x 100 (market condition only;
    data coverage is a separate rule below); below 50 -> cash
  * selection: READY members above their SMA(trend), top N by score (ties: lower instrument id)
  * weight 1/N each, the unfilled slots stay cash; the first session of each calendar month
    rebalances (decided at that close, filled at the next open). A run's first month-start is the
    first month change it observes: it never rebalances on an arbitrary first day.
  * over 5% of members unready on a decision day is an explicit DataNotReady, never a quiet skip
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import ROUND_DOWN, Decimal
from typing import Any, Literal

from algo.data.universe import Interval
from algo.strategy.base import Requirements, Strategy, StrategyParams, Targets
from algo.strategy.context import Context

MIN_BARS = 253  # today + 252 prior sessions: the longest lookback (252) and the eligibility rule
SKIP = 21
BREADTH_SMA = 200
BREADTH_MIN = Decimal(50)
MAX_UNREADY = Decimal("0.05")
LOOKBACK_DAYS = 440  # calendar days; comfortably holds 253 sessions across holidays
WEIGHT_STEP = Decimal("1e-9")


class DataNotReady(Exception):
    """The data cannot support a decision; the run stops rather than guessing."""


class IntervalMembership:
    """Who was in the index on a day, from effective-dated intervals (data only)."""

    def __init__(
        self, intervals: Sequence[Interval], unusable: Mapping[date, str] | None = None
    ) -> None:
        self._ivs = tuple(intervals)
        self._unusable = dict(unusable or {})  # sessions whose membership evidence is unusable

    def unusable_reason(self, day: date) -> str | None:
        """Why a strict decision on `day` may not use this membership (None: usable)."""
        return self._unusable.get(day)

    def on(self, day: date) -> frozenset[int]:
        return frozenset(
            i.instrument_id for i in self._ivs if i.start <= day and (i.end is None or day < i.end)
        )

    def ever(self) -> list[int]:
        return sorted({i.instrument_id for i in self._ivs})

    def intervals(self) -> tuple[Interval, ...]:
        return self._ivs

    def first_day(self) -> date | None:
        """The first day anyone is a member (None when nobody ever is)."""
        return min((i.start for i in self._ivs), default=None)


class MomentumParams(StrategyParams):
    lookback: Literal[126, 189, 252]
    trend_sma: Literal[100, 200]
    holdings: Literal[20, 30]


class PlainParams(StrategyParams):
    """The baseline is fixed: 12-1 momentum, top 20, no filters."""

    lookback: Literal[252] = 252
    holdings: Literal[20] = 20


def _mean(xs: list[Decimal]) -> Decimal:
    return sum(xs, Decimal(0)) / len(xs)


def decide(
    ctx: Context, membership: IntervalMembership, lookback: int, holdings: int,
    trend_sma: int | None,
) -> tuple[Targets, dict[str, Any]]:  # fmt: skip
    day = ctx.now().date()
    members = sorted(membership.on(day))
    if not members:
        raise DataNotReady(f"no members of the universe on {day}")
    hist = ctx.data.history(members, LOOKBACK_DAYS)
    seen = Counter(b.ts.date() for bars in hist.values() for b in bars)
    with_bars = sum(1 for bars in hist.values() if bars)
    cal = sorted(d for d, n in seen.items() if n * 2 >= with_bars)
    window = cal[-MIN_BARS:] if len(cal) >= MIN_BARS else None

    closes: dict[int, list[Decimal]] = {}
    insufficient: list[int] = []
    gap: list[int] = []
    for iid in members:
        bars = hist.get(iid, [])
        if window is None or not bars or bars[0].ts.date() > window[0]:
            insufficient.append(iid)
            continue
        by_day = {b.ts.date(): b.close for b in bars}
        series = [by_day.get(d) for d in window]
        if any(c is None or c <= 0 for c in series):
            gap.append(iid)
        else:
            closes[iid] = [c for c in series if c is not None]

    unready = len(insufficient) + len(gap)
    if Decimal(unready) / Decimal(len(members)) > MAX_UNREADY:
        raise DataNotReady(
            f"{unready} of {len(members)} members unready on {day} "
            f"(insufficient history {len(insufficient)}, data gap {len(gap)})"
        )

    above200 = sum(1 for c in closes.values() if c[-1] > _mean(c[-BREADTH_SMA:]))
    breadth = Decimal(above200) / Decimal(len(closes)) * 100
    ranked: list[tuple[Decimal, int]] = []
    for iid, c in closes.items():
        if trend_sma is not None and not c[-1] > _mean(c[-trend_sma:]):
            continue
        ranked.append((c[-1 - SKIP] / c[-1 - lookback] - 1, iid))
    ranked.sort(key=lambda r: (-r[0], r[1]))
    cash = trend_sma is not None and breadth < BREADTH_MIN
    chosen = [] if cash else [iid for _, iid in ranked[:holdings]]
    weight = (Decimal(1) / holdings).quantize(WEIGHT_STEP, ROUND_DOWN)
    audit = {
        "day": str(day), "members": len(members), "ready": len(closes),
        "insufficient_history": len(insufficient), "data_gap": gap, "breadth": breadth,
        "selected": chosen,
    }  # fmt: skip
    return {iid: weight for iid in chosen}, audit


class _Monthly(Strategy):
    """Shared schedule: the first session of each calendar month rebalances."""

    lookback: int
    holdings: int
    trend_sma: int | None

    def __init__(self, params: StrategyParams, membership: IntervalMembership) -> None:
        super().__init__(params)
        self.membership = membership
        self.audit: list[dict[str, Any]] = []
        self._prev: date | None = None

    def universe(self, ctx: Context) -> list[int]:
        return self.membership.ever()

    def requirements(self) -> Requirements:
        return Requirements(lookback_days=LOOKBACK_DAYS, adjust="split")

    def on_schedule(self, ctx: Context) -> Targets | None:
        d, prev = ctx.now().date(), self._prev
        self._prev = d
        if prev is None or (prev.year, prev.month) == (d.year, d.month):
            return None  # not a month start (or the first session seen: month change unknown)
        why = self.membership.unusable_reason(d)
        if (
            ctx.mode == "strict" and why is not None
        ):  # incomplete / unpublished / unverified evidence
            self.audit.append(
                {"day": str(d), "skipped": "strict: membership evidence unusable", "reasons": why}
            )
            return None  # no decision: current positions are held
        targets, row = decide(ctx, self.membership, self.lookback, self.holdings, self.trend_sma)
        self.audit.append(row)
        return targets


class Nifty200TrendMomentum(_Monthly):
    id, version, Params = "nifty200_trend_momentum", "1", MomentumParams

    def __init__(self, params: MomentumParams, membership: IntervalMembership) -> None:
        super().__init__(params, membership)
        self.lookback, self.holdings, self.trend_sma = (
            params.lookback, params.holdings, params.trend_sma,
        )  # fmt: skip


class PlainMomentum(_Monthly):
    id, version, Params = "momentum_12_1_baseline", "1", PlainParams

    def __init__(self, params: PlainParams, membership: IntervalMembership) -> None:
        super().__init__(params, membership)
        self.lookback, self.holdings, self.trend_sma = params.lookback, params.holdings, None
