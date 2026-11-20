# ruff: noqa: E501
"""Trend ride (long-only, daily): say where each stock's trend is, buy a fresh high only inside an uptrend, and ride it until a trailing stop or the trend line breaks.

Built for the question "where is the trend, and when do I enter or leave?", not "which stocks beat the market over 20 sessions": judge it by
expectancy per trade, drawdown and time in the market, not by outperformance rank. UNVALIDATED until a study says otherwise.

Every rule is STATELESS, computed from price history and the current holdings (a restart decides the same thing). Rules (fixed, versioned with `version`):
  * universe: point-in-time members on the decision day
  * READY: a bar today and WARMUP sessions of history; others are reported, never silently dropped
  * trend state, per stock: UP = close over EMA(50) and EMA(50) at least SLOPE_MIN higher than SLOPE_LAG sessions ago; DOWN = the mirror image; otherwise RANGE
  * entry: READY, not held, state UP, close above the highest close of the previous `breakout` sessions, and close above its stop (so it is never bought and sold the same night);
    the tightest stop first (smallest distance to the stop as a share of the close; ties: lower instrument id)
  * exit (held names): left the universe, or close at or under the chandelier stop (highest high of the last 22 sessions minus `atr_mult` x ATR(14)) = "stop_hit", or close under EMA(50) = "trend_lost".
    The stop is recomputed from history, so no entry price is remembered
  * a held name with no bar today is kept (it cannot be traded); sizing: max_positions slots of 1/max_positions each; over 5% of members unready is an explicit DataNotReady
Decided after each session's close, filled at the next open by the engine (or the paper runner)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any, Literal

from algo.data.reader import AdjBar
from algo.indicators import core
from algo.strategies.nifty200_momentum import DataNotReady, IntervalMembership
from algo.strategy.base import Requirements, Strategy, StrategyParams, Targets
from algo.strategy.context import Context

LOOKBACK_DAYS = (
    200  # calendar days: ~135 sessions, ample for EMA(50), its slope and a 55-session high
)
WARMUP = 80  # sessions before the values are used
TREND_EMA, SLOPE_LAG, STOP_WINDOW, ATR_LEN = 50, 10, 22, 14
SLOPE_MIN = Decimal(
    "0.005"
)  # EMA(50) must move this share in SLOPE_LAG sessions to count as rising or falling; less is RANGE
MAX_UNREADY = Decimal("0.05")
WEIGHT_STEP = Decimal("1e-9")


class TrendRideParams(StrategyParams):
    breakout: Literal[20, 55] = 20
    atr_mult: Literal[2, 3, 4] = 3
    max_positions: Literal[5, 10, 20] = 10


@dataclass(frozen=True)
class Reading:
    state: Literal["UP", "DOWN", "RANGE"]
    new_high: bool  # close above the highest close of the previous `breakout` sessions
    close: Decimal
    ema: Decimal
    stop: Decimal  # chandelier stop


def reading(bars: Sequence[AdjBar], breakout: int, atr_mult: int) -> Reading | None:
    """Where the trend is and where the stop sits on the last bar, or None with too little history."""
    if len(bars) < WARMUP:
        return None
    close = [b.close for b in bars]
    ema = core.ema(close, TREND_EMA)
    atr = core.rma(core.true_range([b.high for b in bars], [b.low for b in bars], close), ATR_LEN)[
        -1
    ]
    top = core.highest([b.high for b in bars], STOP_WINDOW)[-1]
    now, before = ema[-1], ema[-1 - SLOPE_LAG]
    if now is None or before is None or atr is None or top is None:
        return None  # pragma: no cover  (WARMUP sessions always settle all four)
    up = close[-1] > now and now > before * (1 + SLOPE_MIN)
    down = close[-1] < now and now < before * (1 - SLOPE_MIN)
    return Reading(
        "UP" if up else "DOWN" if down else "RANGE",
        close[-1] > max(close[-1 - breakout : -1]),
        close[-1],
        now,
        top - atr_mult * atr,
    )


def decide(
    ctx: Context, membership: IntervalMembership, p: TrendRideParams
) -> tuple[Targets, dict[str, Any]]:
    day = ctx.now().date()
    members = sorted(membership.on(day))
    if not members:
        raise DataNotReady(f"no members of the universe on {day}")
    held = set(ctx.portfolio.positions)
    hist = ctx.data.history(members, LOOKBACK_DAYS)
    ready: dict[int, Reading] = {}
    not_ready: list[int] = []
    for iid in members:
        bars = hist.get(iid, [])
        r = reading(bars, p.breakout, p.atr_mult) if bars and bars[-1].ts.date() == day else None
        if r is None:
            not_ready.append(iid)
        else:
            ready[iid] = r
    if Decimal(len(not_ready)) / Decimal(len(members)) > MAX_UNREADY:
        raise DataNotReady(f"{len(not_ready)} of {len(members)} members unready on {day}")

    def risk(r: Reading) -> Decimal:  # distance to the stop as a share of the close
        return (r.close - r.stop) / r.close

    keep: list[int] = []
    exits: dict[int, str] = {}
    for iid in sorted(held):
        if iid not in members:
            exits[iid] = "left_universe"
        elif iid not in ready:
            keep.append(iid)  # no bar today: it cannot be traded, so it is held as is
        elif ready[iid].close <= ready[iid].stop:
            exits[iid] = "stop_hit"
        elif ready[iid].close < ready[iid].ema:
            exits[iid] = "trend_lost"
        else:
            keep.append(iid)
    if (
        len(keep) > p.max_positions
    ):  # a position still being sold down can keep the count above the limit: keep the tightest stops, names with no bar first
        ranked = sorted(keep, key=lambda i: (risk(ready[i]) if i in ready else Decimal(-1), i))
        dropped = set(ranked[p.max_positions :])
        exits.update({i: "over_limit" for i in dropped})
        keep = [i for i in keep if i not in dropped]
    candidates = sorted(
        (risk(r), iid)
        for iid, r in ready.items()
        if iid not in held and r.state == "UP" and r.new_high and r.close > r.stop
    )
    entries = [iid for _, iid in candidates[: max(p.max_positions - len(keep), 0)]]
    weight = (Decimal(1) / p.max_positions).quantize(WEIGHT_STEP, ROUND_DOWN)
    audit = {
        "day": str(day),
        "members": len(members),
        "ready": len(ready),
        "not_ready": not_ready,
        "held": sorted(held),
        "states": dict(Counter(r.state for r in ready.values())),
        "stops": {i: str(ready[i].stop) for i in keep if i in ready},
        "exits": exits,
        "entries": entries,
    }
    return {iid: weight for iid in keep + entries}, audit


class TrendRide(Strategy):
    id, version, Params = "trend_ride", "1", TrendRideParams

    def __init__(self, params: TrendRideParams, membership: IntervalMembership) -> None:
        super().__init__(params)
        self.p, self.membership = params, membership
        self.audit: list[dict[str, Any]] = []

    @classmethod
    def required_history(cls, params: dict[str, Any]) -> int:
        return WARMUP

    def universe(self, ctx: Context) -> list[int]:
        return self.membership.ever()

    def requirements(self) -> Requirements:
        return Requirements(lookback_days=LOOKBACK_DAYS, adjust="split")

    def on_schedule(self, ctx: Context) -> Targets | None:
        day = ctx.now().date()
        why = self.membership.unusable_reason(day)
        if ctx.mode == "strict" and why is not None:
            self.audit.append(
                {"day": str(day), "skipped": "strict: membership evidence unusable", "reasons": why}
            )
            return None
        targets, row = decide(ctx, self.membership, self.p)
        self.audit.append(row)
        return targets
