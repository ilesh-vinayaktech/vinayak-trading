# ruff: noqa: E501
"""EMA 9/21 cross + MACD turn (long-only, daily), the owner's rule; scripts/study_ema_macd_exit.py found NO edge on 2019-2024 (net excess -0.49% a trade): UNVALIDATED, here to be looked at and studied, not trusted.

Every rule is STATELESS, computed from price history and the current holdings (a restart decides the same thing). Rules (fixed, versioned with `version`):
  * universe: point-in-time members on the decision day
  * READY: a bar today and WARMUP sessions of history; others are reported, never silently dropped
  * entry: READY, not held, EMA(9) over EMA(21) and MACD(12,26,9) over its signal today, and each of the two CROSSED up within the last `cross_window` sessions (today included);
    the strongest first (largest EMA gap as a share of the close; ties: lower instrument id)
  * exit (held names): left the universe, or MACD back under its signal, or EMA(9) back under EMA(21). There is no price stop (entry prices are deliberately not remembered)
  * a held name with no bar today is kept (it cannot be traded); sizing: max_positions slots of 1/max_positions each; over 5% of members unready is an explicit DataNotReady
Decided after each session's close, filled at the next open by the engine (or the paper runner)."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_DOWN, Decimal
from typing import Any, Literal

from algo.data.reader import AdjBar
from algo.indicators import catalog, core
from algo.strategies.nifty200_momentum import DataNotReady, IntervalMembership
from algo.strategy.base import Requirements, Strategy, StrategyParams, Targets
from algo.strategy.context import Context

LOOKBACK_DAYS = (
    200  # calendar days: ~135 sessions, ample for the 26-day EMA and MACD signal to settle
)
WARMUP = 60  # sessions before the values are used
MAX_UNREADY = Decimal("0.05")
WEIGHT_STEP = Decimal("1e-9")


class EmaMacdCrossParams(StrategyParams):
    cross_window: Literal[3, 5] = 3
    max_positions: Literal[5, 10, 20] = 10


def _state(bars: Sequence[AdjBar], window: int) -> tuple[bool, bool, Decimal] | None:
    """(both up today, a fresh cross of both inside the window, EMA gap as a share of the close), or None with too little history."""
    if len(bars) < WARMUP:
        return None
    close = [b.close for b in bars]
    e9, e21 = core.ema(close, 9), core.ema(close, 21)
    out = catalog.compute(
        "macd",
        catalog.Bars(
            [b.open for b in bars],
            [b.high for b in bars],
            [b.low for b in bars],
            close,
            [b.volume for b in bars],
        ),
    )[2]
    line, sig = out["macd"], out["signal"]
    if None in (e9[-1], e21[-1], line[-1], sig[-1]):
        return None
    up_e = [a is not None and b is not None and a > b for a, b in zip(e9, e21, strict=True)]
    up_m = [a is not None and b is not None and a > b for a, b in zip(line, sig, strict=True)]

    def crossed(up: list[bool]) -> bool:
        return any(up[i] and not up[i - 1] for i in range(len(up) - window, len(up)))

    gap = (e9[-1] - e21[-1]) / close[-1]  # type: ignore[operator]
    return up_e[-1] and up_m[-1], crossed(up_e) and crossed(up_m), gap


def decide(
    ctx: Context, membership: IntervalMembership, p: EmaMacdCrossParams
) -> tuple[Targets, dict[str, Any]]:
    day = ctx.now().date()
    members = sorted(membership.on(day))
    if not members:
        raise DataNotReady(f"no members of the universe on {day}")
    held = set(ctx.portfolio.positions)
    hist = ctx.data.history(members, LOOKBACK_DAYS)
    ready: dict[int, tuple[bool, bool, Decimal]] = {}
    not_ready: list[int] = []
    for iid in members:
        bars = hist.get(iid, [])
        state = _state(bars, p.cross_window) if bars and bars[-1].ts.date() == day else None
        if state is None:
            not_ready.append(iid)
        else:
            ready[iid] = state
    if Decimal(len(not_ready)) / Decimal(len(members)) > MAX_UNREADY:
        raise DataNotReady(f"{len(not_ready)} of {len(members)} members unready on {day}")

    keep: list[int] = []
    exits: dict[int, str] = {}
    for iid in sorted(held):
        if iid not in members:
            exits[iid] = "left_universe"
        elif iid not in ready:
            keep.append(iid)  # no bar today: it cannot be traded, so it is held as is
        elif not ready[iid][0]:
            exits[iid] = "macd_or_ema_turned_down"
        else:
            keep.append(iid)
    if (
        len(keep) > p.max_positions
    ):  # a position still being sold down can keep the count above the limit: keep the strongest, names with no bar first
        ranked = sorted(keep, key=lambda i: (-(ready[i][2] if i in ready else Decimal(10)), i))
        dropped = set(ranked[p.max_positions :])
        exits.update({i: "over_limit" for i in dropped})
        keep = [i for i in keep if i not in dropped]
    candidates = sorted(
        (
            (-gap, iid)
            for iid, (up, fresh, gap) in ready.items()
            if iid not in held and up and fresh
        ),
        key=lambda r: (r[0], r[1]),
    )
    entries = [iid for _, iid in candidates[: max(p.max_positions - len(keep), 0)]]
    weight = (Decimal(1) / p.max_positions).quantize(WEIGHT_STEP, ROUND_DOWN)
    audit = {
        "day": str(day),
        "members": len(members),
        "ready": len(ready),
        "not_ready": not_ready,
        "held": sorted(held),
        "exits": exits,
        "entries": entries,
    }
    return {iid: weight for iid in keep + entries}, audit


class EmaMacdCross(Strategy):
    id, version, Params = "ema_macd_cross", "1", EmaMacdCrossParams

    def __init__(self, params: EmaMacdCrossParams, membership: IntervalMembership) -> None:
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
