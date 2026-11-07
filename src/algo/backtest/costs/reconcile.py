"""Reconcile simulated charges against a broker's contract note (the acceptance test for the cost
engine). Compare component totals for one trading day's orders. A difference is explainable only as
paisa rounding: the engine rounds each component per order, a contract note may round on day totals,
so up to `tolerance_per_order` per order is allowed - anything larger, or a component present on one
side only, is a real discrepancy and fails the reconciliation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from algo.backtest.costs.policy import CostPolicy

PAISA = Decimal("0.01")


@dataclass(frozen=True)
class Difference:
    type: str
    computed: Decimal
    reported: Decimal

    @property
    def delta(self) -> Decimal:
        return self.computed - self.reported


@dataclass(frozen=True)
class NoteReconciliation:
    day: date
    orders: int
    allowed: Decimal  # rounding allowance per component = tolerance_per_order x orders
    rounding_only: tuple[Difference, ...]  # non-zero but within the allowance
    discrepancies: tuple[Difference, ...]  # beyond rounding, or present on one side only

    @property
    def ok(self) -> bool:
        return not self.discrepancies


def reconcile_note(
    cost: CostPolicy,
    day: date,
    orders: Sequence[tuple[str, Decimal, Decimal]],  # (side, qty, price) as executed
    reported: Mapping[str, Decimal],  # component totals printed on the contract note
    *,
    tolerance_per_order: Decimal = PAISA,
) -> NoteReconciliation:
    if not orders:
        raise ValueError("a contract note needs at least one order")
    computed: dict[str, Decimal] = defaultdict(Decimal)
    brokerage = Decimal(0)
    for side, qty, price in orders:
        ch = cost.charges(day, side, qty, price)
        brokerage += ch.amount("BROKERAGE")
        for line in ch.lines:
            computed[line.type] += line.amount
    top_up = cost.note_shortfall(day, brokerage)
    if top_up > 0:
        computed["BROKERAGE"] += top_up
    allowed = tolerance_per_order * len(orders)
    rounding, bad = [], []
    for type_ in sorted(set(computed) | set(reported)):
        d = Difference(type_, computed.get(type_, Decimal(0)), reported.get(type_, Decimal(0)))
        one_sided = (type_ in computed) != (type_ in reported)
        if one_sided and d.delta != 0:
            bad.append(d)
        elif abs(d.delta) > allowed:
            bad.append(d)
        elif d.delta != 0:
            rounding.append(d)
    return NoteReconciliation(day, len(orders), allowed, tuple(rounding), tuple(bad))
