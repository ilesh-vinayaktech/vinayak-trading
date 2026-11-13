# ruff: noqa: E501
"""A screener used as a strategy, run the way every strategy runs: after each session close it runs the screen on that day's
data. A held stock that no longer matches is sold; a free slot (`max_positions` in all) goes to the best-ranked match not
held yet. Nothing waits for a calendar date. Held stocks that still match, and a day on which nothing changes, return None,
so no order is proposed for mere price drift. Stateless: it reads what is held, so a runner that builds a fresh strategy each
session decides the same as one that ran all along.

The screen is part of the locked study (not code), so the owner builds it the way they build a screen on the Screener page.
A screen may use price fields (technicals), filed ratios (fundamentals) or both. Technicals are computed here, per day, from
split-adjusted bars the Context bounds to that day. Fundamentals come from a `FundamentalsBook` of the filings known on that
day (a restatement counts once filed), through the same `algo.data.ratios` code the Screener page uses; never from today's
Screener table, which would leak the future. Both read as the Screener page reads them.
Ties go to the lower instrument id. Decided after the close, filled at the next open by the engine."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, time
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from algo.data.reader import IST
from algo.indicators.catalog import Bars
from algo.screener import engine
from algo.screener.technical import technicals
from algo.strategies.fundamentals import FundamentalsBook
from algo.strategies.nifty200_momentum import IntervalMembership
from algo.strategy.base import Requirements, Strategy, StrategyParams, Targets
from algo.strategy.context import Context

LOOKBACK_DAYS = (
    420  # calendar days: holds the 252 sessions the longest technical (1-year change) reads
)
WEIGHT_STEP = Decimal("1e-9")
KEPT_STEP = Decimal(
    "1e-12"
)  # finer, so a full account of kept stocks stays inside the engine's 1e-9 tolerance


class ScreenerParams(StrategyParams):
    max_positions: Literal[5, 10, 20] = 10


class ConditionSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    field: str
    op: str
    value: Any


class ScreenSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    conditions: list[ConditionSpec] = Field(min_length=1, max_length=20)
    match: Literal["all", "any"] = "all"
    sort: str  # the field the best matches are ranked on
    descending: bool = True

    def fields_used(self) -> set[str]:
        """The fields the conditions and the ranking read: all that has to be worked out for a stock."""
        return {c.field for c in self.conditions} | {self.sort}

    def needs_fundamentals(self) -> bool:
        return any(
            engine.FIELDS[f].kind == "fundamental" for f in self.fields_used() if f in engine.FIELDS
        )

    def engine_conditions(self) -> list[engine.Condition]:
        return [engine.Condition(c.field, c.op, c.value) for c in self.conditions]

    def problem(self) -> str | None:
        """Why this screen cannot be run, or None: a field must be a price field or a filed ratio. A market-cap class is not one
        (a study and a saved strategy both pick their market-cap segments separately)."""
        bad = sorted(
            f for f in self.fields_used()
            if f not in engine.FIELDS or engine.FIELDS[f].kind not in ("technical", "fundamental")
        )  # fmt: skip
        if bad:
            return f"{', '.join(bad)}: unknown, or a market-cap class (choose the market-cap segments separately)"
        try:
            for c in self.engine_conditions():
                engine.validate(c)
        except engine.ScreenError as e:
            return str(e)
        return None


def still_matches(
    spec: ScreenSpec,
    bars: Sequence[Any],
    book: FundamentalsBook | None = None,
    iid: int | None = None,
) -> bool:
    """Does the screen's condition set hold for this stock on the last of `bars` (oldest first)? Filed ratios are read from
    `book` (as known at the end of that day) when it is given."""
    cols = [[getattr(b, k) for b in bars] for k in ("open", "high", "low", "close", "volume")]
    row = technicals(Bars(*cols), spec.fields_used())
    if book is not None and iid is not None:
        day = bars[-1].ts.astimezone(IST).date()
        row.update(book.ratios(iid, datetime.combine(day, time.max, IST), bars[-1].close, day))
    hit, _ = engine.run([row], spec.engine_conditions(), match=spec.match, limit=1)
    return bool(hit)


class ScreenerStrategy(Strategy):
    id, version, Params = "screener", "3", ScreenerParams

    def __init__(
        self,
        params: ScreenerParams,
        membership: IntervalMembership,
        screen: ScreenSpec,
        book: FundamentalsBook | None = None,
    ) -> None:
        super().__init__(params)
        if book is None and screen.needs_fundamentals():
            raise ValueError("this screen reads filed ratios: it needs a FundamentalsBook")
        self.p, self.membership, self.screen, self.book = params, membership, screen, book
        self.audit: list[
            dict[str, Any]
        ] = []  # one entry per change: who entered, who left (the paper runner records it)

    def universe(self, ctx: Context) -> list[int]:
        return self.membership.ever()

    def requirements(self) -> Requirements:
        return Requirements(lookback_days=LOOKBACK_DAYS, adjust="split")

    def on_schedule(self, ctx: Context) -> Targets | None:
        day = ctx.now().date()
        if ctx.mode == "strict" and self.membership.unusable_reason(day) is not None:
            return None
        held = set(ctx.portfolio.positions)
        wanted = sorted(
            set(self.membership.on(day)) | held
        )  # a held stock is checked even if it left the universe
        hist = ctx.data.history(wanted, LOOKBACK_DAYS)
        rows = []
        for iid in wanted:
            bars = hist.get(iid)
            if bars and bars[-1].ts.date() == day:
                cols = [
                    [getattr(b, k) for b in bars]
                    for k in ("open", "high", "low", "close", "volume")
                ]
                row = {"instrument_id": iid, **technicals(Bars(*cols), self.screen.fields_used())}
                if self.book is not None:
                    row.update(self.book.ratios(iid, ctx.now(), bars[-1].close, day))
                rows.append(row)
        if not rows:
            return None  # no data today: decide on the next session
        matched, _ = engine.run(
            rows, self.screen.engine_conditions(), match=self.screen.match, sort=self.screen.sort,
            descending=self.screen.descending, limit=len(rows),
        )  # fmt: skip
        ranked = [r["instrument_id"] for r in matched]  # every match, best first
        traded = {r["instrument_id"] for r in rows}
        # a held stock with no bar today cannot be traded, so it stays; the others stay while they match
        keep = sorted(i for i in held if i not in traded) + [i for i in ranked if i in held]
        keep = keep[: self.p.max_positions]  # more held than slots: the best ranked stay
        entries = [i for i in ranked if i not in held][: self.p.max_positions - len(keep)]
        slot = (Decimal(1) / self.p.max_positions).quantize(WEIGHT_STEP, ROUND_DOWN)
        price = {r["instrument_id"]: r["price"] for r in rows}
        equity = ctx.portfolio.equity

        def current(iid: int) -> Decimal:
            """A stock that stays is returned at what it is worth now, so the runner does not resize it: orders are for stocks
            that enter or leave, not for price drift. Rounded up, finely: a hair above its size never rounds a whole share
            away, and many of them still add up to no more than the engine's 1e-9 tolerance."""
            px = price.get(iid)
            if px is None or equity <= 0:
                return slot  # no price today (it cannot be traded) or no value to measure against
            return (ctx.portfolio.positions[iid] * px / equity).quantize(KEPT_STEP, ROUND_UP)

        kept = {iid: current(iid) for iid in keep}
        # new entries get a full slot, but never more than the room the kept stocks leave: winners grow past a slot
        room = Decimal(1) - sum(kept.values(), Decimal(0))
        each = (
            min(slot, (room / len(entries)).quantize(WEIGHT_STEP, ROUND_DOWN)) if entries else slot
        )
        if each <= 0:
            entries = []  # the account is full: nothing can be bought until something is sold
        target = set(kept) | set(entries)
        if target == held:
            return None  # nothing entered or left: no order for price drift
        self.audit.append({
            "entries": entries, "exits": {i: "no longer matches the screen" for i in sorted(held - target)},
            "entry_reason": "entry: matches the screen",
        })  # fmt: skip
        return {**kept, **{iid: each for iid in entries}}
