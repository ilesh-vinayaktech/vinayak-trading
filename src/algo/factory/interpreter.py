# ruff: noqa: E501
"""Runs a strategy definition (algo.factory.dsl) as an ordinary Strategy: a deterministic interpreter, no generated code.

Callers: tests/unit/factory/test_interpreter.py, the backtest engine and the paper runner (through the Strategy contract), algo.factory.registry.
User's instruction: "do as much as you can do yourself, keep taking things one by one from @TODO.md and @plan.md ... keep things finishing with test".

Rules (fixed, the same for every definition):
  * READY: a bar on the decision day and a value for every feature the definition reads. A stock still short of history (or with a gap in its window) is
    WARMING UP: never an entry, reported, not dropped silently. A stock with no bar today cannot be traded: if held it is carried as it is.
  * Over 5% of the members with no bar on the day is an explicit DataNotReady, never a quiet skip (a data outage must not look like 'no signals').
  * Exit (held, ready): the exit group is true. A held stock that left the universe is sold. The rest are kept.
  * Entry (not held, ready): the entry group is true; the best by the ranking fill the free slots (ties: lower instrument id).
  * More holdings than slots (positions still being sold down): the worst ranked are dropped; stocks that cannot be traded are kept first.
  * Sizing: EQUAL_WEIGHT gives each position min(1/max_positions, cap). INVERSE_VOLATILITY spreads the slots' combined share in proportion to 1 / vol_20d,
    each capped; a stock without a usable volatility gets the equal share. Whatever is left stays cash.
  * Features are the registered feature functions themselves, evaluated on the bars Context serves (adjusted as of the decision day). Version 1 allows
    only features whose value depends on a fixed window, so evaluating them on a trimmed history is exact."""

from __future__ import annotations

import operator
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from decimal import ROUND_DOWN, Decimal
from math import ceil
from typing import Any

from algo.data.reader import AdjBar
from algo.factory.dsl import (
    BREADTH_SOURCE,
    MARKET_BREADTH,
    MARKET_FEATURES,
    PERCENT_OPS,
    VOLATILITY_FEATURE,
    Group,
    Ranking,
    StrategyDef,
)
from algo.features import registry as feature_registry
from algo.features._shared import SessionBar
from algo.strategies.nifty200_momentum import DataNotReady, IntervalMembership
from algo.strategy.base import Requirements, Strategy, StrategyParams, Targets
from algo.strategy.context import Context

MAX_NO_BAR = Decimal("0.05")
WEIGHT_STEP = Decimal("1e-9")
OPS: dict[str, Callable[[Decimal, Decimal], bool]] = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}
Values = dict[int, dict[str, Decimal]]


Cross = dict[tuple[str, str, Decimal], set[int]]


def _cross_sections(defn: StrategyDef, ready: Values) -> Cross:
    """For every percentile condition in the definition, the stocks that satisfy it TODAY: the strongest (TOP_PERCENT) or weakest (BOTTOM_PERCENT) `value`% of the ready stocks by that
    feature, rounded UP to a whole number of stocks (at least one), ties going to the lower instrument id. Worked out from today's values only, so there is nothing to look ahead to."""
    out: Cross = {}
    for c in defn.entry.conditions() + defn.exit.conditions():
        key = (c.feature, c.op, c.value)
        if c.op not in PERCENT_OPS or key in out or not ready:
            continue
        take = max(1, ceil(Decimal(len(ready)) * c.value / 100))
        sign = -1 if c.op == "TOP_PERCENT" else 1
        order = sorted(ready, key=lambda i: (sign * ready[i][c.feature], i))
        out[key] = set(order[:take])
    return out


def _holds(
    group: Group, values: Mapping[str, Decimal], iid: int | None = None, cross: Cross | None = None
) -> bool:
    results = [
        iid in (cross or {}).get((c.feature, c.op, c.value), set())
        if c.op in PERCENT_OPS
        else OPS[c.op](values[c.feature], c.value)
        for c in group.conditions()
    ]
    return all(results) if group.mode() == "all" else any(results)


def _session_bars(bars: Sequence[AdjBar]) -> dict[date, SessionBar]:
    out: dict[date, SessionBar] = {}
    for b in bars:
        d = b.ts.date()
        out[d] = SessionBar(
            d, b.high, b.low, b.close, b.close, b.volume, b.ts
        )  # raw value traded = adjusted price x adjusted volume (the factor cancels)
    return out


def _uses_market(defn: StrategyDef) -> bool:
    return any(
        c.feature in MARKET_FEATURES for c in defn.entry.conditions() + defn.exit.conditions()
    )


def _features(
    defn: StrategyDef, members: Sequence[int], hist: Mapping[int, Sequence[AdjBar]], day: date
) -> tuple[Values, list[int], list[int]]:
    """(values of every ready member, members with no bar on `day`, members still warming up)."""
    sbars = {i: _session_bars(hist[i]) for i in members if hist.get(i)}
    no_bar = sorted(i for i in members if day not in sbars.get(i, {}))
    present = {i: b for i, b in sbars.items() if day in b}
    sessions = [d for d in feature_registry.sessions_from(sbars) if d <= day][
        -(defn.warmup_bars() + 2) :
    ]
    needed = sorted(defn.required_features())
    ready: Values = {}
    warming: list[int] = []
    for i in sorted(present):
        row: dict[str, Decimal] = {}
        for name in needed:
            got = feature_registry.DEFINITIONS[name].compute(sessions, present[i]).get(day)
            if got is not None:
                row[name] = got[0]
        if len(row) == len(needed):
            ready[i] = row
        else:
            warming.append(i)
    if ready and _uses_market(
        defn
    ):  # the market filter: how many of today's ready stocks sit above their own 200-day average
        breadth = (
            Decimal(100) * sum(1 for r in ready.values() if r[BREADTH_SOURCE] > 0) / len(ready)
        )
        for r in ready.values():
            r[MARKET_BREADTH] = breadth
    return ready, no_bar, warming


def _best_first(ranking: Ranking, ready: Values) -> Callable[[int], tuple[Any, ...]]:
    sign = -1 if ranking.order == "DESC" else 1
    return lambda i: (sign * ready[i][ranking.feature], i)


def decide(
    defn: StrategyDef,
    members: Sequence[int],
    hist: Mapping[int, Sequence[AdjBar]],
    held: set[int],
    day: date,
    *,
    features: tuple[Values, list[int], list[int]] | None = None,
) -> tuple[Targets, dict[str, Any]]:
    """`features`: the day's (ready, no_bar, warming) when already worked out (a later run of the same study, which differs only in its settings); `hist` is then not read."""
    if not members:
        raise DataNotReady(f"no members of the universe on {day}")
    ready, no_bar, warming = (
        features if features is not None else _features(defn, members, hist, day)
    )
    if Decimal(len(no_bar)) / Decimal(len(members)) > MAX_NO_BAR:
        raise DataNotReady(f"{len(no_bar)} of {len(members)} members have no bar on {day}")
    best = _best_first(defn.ranking, ready)
    cross = _cross_sections(defn, ready)
    slots = defn.position.max_positions
    exits: dict[int, str] = {}
    keep: list[int] = []
    for iid in sorted(held):
        if iid not in members:
            exits[iid] = "left_universe"
        elif iid not in ready:
            keep.append(
                iid
            )  # no bar or not enough data today: it cannot be traded, so it is carried as it is
        elif _holds(defn.exit, ready[iid], iid, cross):
            exits[iid] = "exit_condition"
        else:
            keep.append(iid)
    if len(keep) > slots:
        order = sorted(
            keep, key=lambda i: (1, best(i)) if i in ready else (0, (0, i))
        )  # untradable names are kept first
        dropped = set(order[slots:])
        exits.update({i: "over_limit" for i in dropped})
        keep = [i for i in keep if i not in dropped]
    candidates = sorted(
        (i for i in ready if i not in held and _holds(defn.entry, ready[i], i, cross)), key=best
    )
    entries = candidates[: max(slots - len(keep), 0)]
    selected = keep + entries
    cap = defn.risk.max_position_percent / 100
    share = Decimal(1) / Decimal(slots)
    flat = min(share, cap)
    weights = {i: flat for i in selected}
    if defn.position.sizing == "INVERSE_VOLATILITY":
        usable = [i for i in selected if i in ready and ready[i][VOLATILITY_FEATURE] > 0]
        if usable:
            budget = share * len(usable)
            inv = {i: 1 / ready[i][VOLATILITY_FEATURE] for i in usable}
            total = sum(inv.values(), Decimal(0))
            weights.update({i: min(cap, budget * inv[i] / total) for i in usable})
    targets = {i: w.quantize(WEIGHT_STEP, ROUND_DOWN) for i, w in weights.items()}
    audit = {
        "day": str(day), "members": len(members), "ready": len(ready), "no_bar": no_bar, "warming_up": warming,
        "held": sorted(held), "exits": exits, "entries": entries,
    }  # fmt: skip
    return targets, audit


class Cadence:
    """Decide once per period: the first call always decides, then again only when the day falls in a new day, ISO week or month."""

    def __init__(self, rebalance: str) -> None:
        self.rebalance = rebalance
        self._last: Any = None

    def _key(self, day: date) -> Any:
        if self.rebalance == "WEEKLY":
            return day.isocalendar()[:2]
        if self.rebalance == "MONTHLY":
            return (day.year, day.month)
        return day

    def due(self, day: date) -> bool:
        key = self._key(day)
        if key == self._last:
            return False
        self._last = key
        return True


class NoParams(StrategyParams):
    """A definition has no separate parameters: everything it is lives in the definition and its hash."""


class DslStrategy(Strategy):
    Params = NoParams

    def __init__(
        self, defn: StrategyDef, membership: IntervalMembership, cache: dict[Any, Any] | None = None
    ) -> None:
        super().__init__(NoParams())
        self.defn, self.membership = defn, membership
        self.cache = cache  # shared by the runs of one study: the day's feature values depend on the data and the stocks, not on the settings
        self.id, self.version = defn.strategy_id, str(defn.version)
        self.cadence = Cadence(defn.rebalance)
        self.audit: list[dict[str, Any]] = []

    @property
    def params_hash(self) -> str:
        return self.defn.sha256[:16]

    def universe(self, ctx: Context) -> list[int]:
        return self.membership.ever()

    def requirements(self) -> Requirements:
        return Requirements(
            lookback_days=ceil(self.defn.warmup_bars() * 7 / 5) + 30, adjust="split"
        )  # calendar days that hold the warm-up across weekends and holidays

    def on_schedule(self, ctx: Context) -> Targets | None:
        day = ctx.now().date()
        why = self.membership.unusable_reason(day)
        if ctx.mode == "strict" and why is not None:
            self.audit.append(
                {"day": str(day), "skipped": "strict: membership evidence unusable", "reasons": why}
            )
            return None
        if not self.cadence.due(day):
            return None  # not a rebalance day: the previous targets stand
        members = sorted(self.membership.on(day))
        key = (tuple(sorted(self.defn.required_features())), day, tuple(members))
        features = self.cache.get(key) if self.cache is not None and ctx.mode != "strict" else None
        hist: Mapping[int, Sequence[AdjBar]] = {}
        if (
            features is None
        ):  # asking for the bars can have effects in strict mode, so the cache is only used outside it
            hist = ctx.data.history(
                members + sorted(set(ctx.portfolio.positions) - set(members)),
                self.requirements().lookback_days,
            )
            if self.cache is not None and ctx.mode != "strict" and members:
                features = _features(self.defn, members, hist, day)
                self.cache[key] = features
        targets, row = decide(
            self.defn, members, hist, set(ctx.portfolio.positions), day, features=features
        )
        self.audit.append(row)
        return targets
