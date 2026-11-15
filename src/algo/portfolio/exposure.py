# ruff: noqa: E501
"""One Book across all strategies (plan.md section 14.3): two strategies holding the same stock must not each slip under a limit that the sum would break.

Callers: tests/unit/portfolio/test_exposure.py; no production caller yet (paper accounts are one strategy each today). User's instruction: "do as much as you can do
yourself, keep taking things one by one from @TODO.md and @plan.md ... keep things finishing with test". Pure: it is handed each strategy's open positions as signed
rupee values and quantities, and builds the `Book` the risk engine already judges orders against. Values are the caller's mark (cost or market), signed (short < 0).
  * The instrument and its sector are summed over EVERY strategy, not just the one placing the order.
  * Gross is the sum of absolute values per instrument AFTER netting across strategies (one long and one short of the same stock net, as the broker's position does);
    net is the plain sum.
  * An instrument with no known sector contributes to no sector's total; the engine already rejects an order whose own sector is unknown."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from algo.risk.model import Book


@dataclass(frozen=True)
class Position:
    qty: int
    value: Decimal  # signed, same sign as qty


def aggregate_book(
    positions: Mapping[str, Mapping[int, Position]],
    *,
    instrument_id: int,
    sector_of: Mapping[int, str | None],
    cash: Decimal,
    open_orders: int = 0,
) -> Book:
    """`positions` is {strategy_id: {instrument_id: Position}}."""
    qty: dict[int, int] = {}
    value: dict[int, Decimal] = {}
    for held in positions.values():
        for iid, p in held.items():
            if p.qty * p.value < 0 or (p.qty == 0) != (p.value == 0):
                raise ValueError(f"instrument {iid}: quantity {p.qty} and value {p.value} disagree")
            qty[iid] = qty.get(iid, 0) + p.qty
            value[iid] = value.get(iid, Decimal(0)) + p.value
    sector = sector_of.get(instrument_id)
    sector_value = (
        Decimal(0)
        if sector is None
        else sum((v for i, v in value.items() if sector_of.get(i) == sector), Decimal(0))
    )
    return Book(
        position_qty=qty.get(instrument_id, 0),
        instrument_value=value.get(instrument_id, Decimal(0)),
        sector_value=sector_value,
        gross_value=sum((abs(v) for v in value.values()), Decimal(0)),
        net_value=sum(value.values(), Decimal(0)),
        margin_available=cash,
        open_orders=open_orders,
    )
