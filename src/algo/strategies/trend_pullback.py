# ruff: noqa: E501
"""Trend-filtered RSI pullback (long-only, daily): buy a Nifty 200 stock that is oversold inside an uptrend, sell when it recovers.

Pure decision logic like the momentum strategy: membership arrives as plain interval data and prices only through Context.
Every rule is STATELESS, computed from price history and the current holdings, so a restart (or the paper runner) decides
the same thing without having to remember entry prices. Rules (fixed, versioned with `version`):
  * universe: point-in-time members on the decision day
  * READY: a bar today and enough history for the trend average; others are reported, never silently dropped
  * trend: close above its SMA(trend_sma)
  * entry: READY, not held, in trend, RSI(5) below entry_rsi; the most oversold first (ties: lower instrument id)
  * exit (held names): left the universe, or lost the trend (close <= SMA), or RSI(5) above exit_rsi. The trend break is
    the only protective stop; there is no price stop because entry prices are deliberately not remembered
  * a held name with no bar today is kept (it cannot be traded) and counted as unready
  * sizing: max_positions slots of 1/max_positions each; unfilled slots stay cash
  * over 5% of members unready on a decision day is an explicit DataNotReady, never a quiet skip
Decided after each session's close, filled at the next open by the engine (or by the paper runner)."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_DOWN, Decimal
from typing import Any, Literal

from algo.data.reader import AdjBar
from algo.indicators import catalog, core
from algo.strategies.nifty200_momentum import DataNotReady, IntervalMembership
from algo.strategy.base import Requirements, Strategy, StrategyParams, Targets
from algo.strategy.context import Context

RSI_LEN = 5
LOOKBACK_DAYS = (
    420  # calendar days; comfortably holds the 200-day average plus warm-up across holidays
)
WARMUP = 10  # sessions beyond the trend average before RSI and SMA are both settled
MAX_UNREADY = Decimal("0.05")
WEIGHT_STEP = Decimal("1e-9")


class TrendPullbackParams(StrategyParams):
    trend_sma: Literal[100, 200] = 200
    entry_rsi: Literal[20, 25, 30] = 25
    exit_rsi: Literal[55, 60, 65] = 60
    max_positions: Literal[5, 10, 20] = 10


_CACHE: dict[tuple[Any, ...], tuple[Decimal, Decimal, Decimal] | None] = {}
_CACHE_MAX = 3_000_000


def clear_indicator_cache() -> None:
    """Forget the memoised indicator values (a study run calls this first, so a changed adjustment is never served stale)."""
    _CACHE.clear()


def _indicators(bars: Sequence[AdjBar], trend: int) -> tuple[Decimal, Decimal, Decimal] | None:
    """(close, SMA(trend), RSI(RSI_LEN)) on the last bar, or None when the history is too short.

    A pure function of the bars it reads, so it is memoised on what identifies them (stock, first and last bar, length, their
    closes, trend): the trials of one study differ in thresholds, not in these values, and share them."""
    if len(bars) < trend + WARMUP:
        return None
    first, last = bars[0], bars[-1]
    key = (last.owner, first.ts, last.ts, len(bars), first.close, last.close, trend)
    if key in _CACHE:
        return _CACHE[key]
    series = catalog.Bars(
        [b.open for b in bars], [b.high for b in bars], [b.low for b in bars],
        [b.close for b in bars], [b.volume for b in bars],
    )  # fmt: skip
    sma = core.sma_last(series.close, trend)
    rsi = catalog.compute(f"rsi:{RSI_LEN}", series)[2]["value"][-1]
    out = None if sma is None or rsi is None else (last.close, sma, rsi)
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.clear()
    _CACHE[key] = out
    return out


def decide(
    ctx: Context, membership: IntervalMembership, p: TrendPullbackParams
) -> tuple[Targets, dict[str, Any]]:
    day = ctx.now().date()
    members = sorted(membership.on(day))
    if not members:
        raise DataNotReady(f"no members of the universe on {day}")
    held = set(ctx.portfolio.positions)
    hist = ctx.data.history(members, LOOKBACK_DAYS)
    ready: dict[int, tuple[Decimal, Decimal, Decimal]] = {}
    not_ready: list[int] = []
    for iid in members:
        bars = hist.get(iid, [])
        values = _indicators(bars, p.trend_sma) if bars and bars[-1].ts.date() == day else None
        if values is None:
            not_ready.append(iid)
        else:
            ready[iid] = values
    if Decimal(len(not_ready)) / Decimal(len(members)) > MAX_UNREADY:
        raise DataNotReady(f"{len(not_ready)} of {len(members)} members unready on {day}")

    keep: list[int] = []
    exits: dict[int, str] = {}
    for iid in sorted(held):
        if iid not in members:
            exits[iid] = "left_universe"
        elif iid not in ready:
            keep.append(iid)  # no bar today: it cannot be traded, so it is held as is
        else:
            close, sma, rsi = ready[iid]
            if not close > sma:
                exits[iid] = "below_trend"
            elif rsi > p.exit_rsi:
                exits[iid] = "rsi_above_exit"
            else:
                keep.append(iid)
    if len(keep) > p.max_positions:
        # A position still being sold down (orders are split by size or volume) is still held while its slot may already be
        # in use, so more than max_positions can be held. Keep the most oversold; names with no bar today are kept first,
        # since they cannot be sold. Without this the targets add up to more than 100% and the run stops.
        ranked = sorted(keep, key=lambda i: (ready[i][2] if i in ready else Decimal(-1), i))
        dropped = set(ranked[p.max_positions :])
        exits.update({i: "over_limit" for i in dropped})
        keep = [i for i in keep if i not in dropped]
    candidates = sorted(
        ((rsi, iid) for iid, (close, sma, rsi) in ready.items() if iid not in held and close > sma and rsi < p.entry_rsi),
        key=lambda r: (r[0], r[1]),
    )  # fmt: skip
    entries = [iid for _, iid in candidates[: max(p.max_positions - len(keep), 0)]]
    weight = (Decimal(1) / p.max_positions).quantize(WEIGHT_STEP, ROUND_DOWN)
    audit = {
        "day": str(day), "members": len(members), "ready": len(ready), "not_ready": not_ready,
        "held": sorted(held), "exits": exits, "entries": entries,
    }  # fmt: skip
    return {iid: weight for iid in keep + entries}, audit


class TrendPullback(Strategy):
    id, version, Params = "trend_pullback", "1", TrendPullbackParams

    def __init__(self, params: TrendPullbackParams, membership: IntervalMembership) -> None:
        super().__init__(params)
        self.p = params
        self.membership = membership
        self.audit: list[dict[str, Any]] = []

    @classmethod
    def required_history(cls, params: dict[str, Any]) -> int:
        """Sessions of history a stock needs before this strategy can decide on it (the longest lookback plus warm-up)."""
        # a grid may leave a parameter out: the study then runs with its default
        trend = params.get("trend_sma", TrendPullbackParams.model_fields["trend_sma"].default)
        return int(trend) + WARMUP

    def universe(self, ctx: Context) -> list[int]:
        return self.membership.ever()

    def requirements(self) -> Requirements:
        return Requirements(lookback_days=LOOKBACK_DAYS, adjust="split")

    def on_schedule(self, ctx: Context) -> Targets | None:
        day = ctx.now().date()
        why = self.membership.unusable_reason(day)
        if (
            ctx.mode == "strict" and why is not None
        ):  # incomplete / unpublished / unverified evidence
            self.audit.append(
                {"day": str(day), "skipped": "strict: membership evidence unusable", "reasons": why}
            )
            return None  # no decision: current positions are held
        targets, row = decide(ctx, self.membership, self.p)
        self.audit.append(row)
        return targets
