# ruff: noqa: E501
"""Flatten: close positions with reduce-only orders when the kill switch says FLATTEN (spec section 11).

Only a strategy whose switch is FLATTEN is touched. Its other open orders are cancelled first (never the closing orders sent for
this same FLATTEN event), then one reduce-only order per position goes through the OMS and so through the risk engine. Each closing order's
intent key carries the time of the FLATTEN event, so running flatten again (after a crash, or every minute) never sends a second
order for the same position, while a later FLATTEN event closes what was bought since. Whether a closing order is a market or a
priced order is the caller's policy (`price_of`); the OMS does not guess."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from algo.execution.oms import Oms
from algo.execution.orders import Order, client_order_id
from algo.risk.killswitch import Mode
from algo.risk.model import Book, Day, Market, OrderRequest, Side


@dataclass
class FlattenReport:
    orders: list[Order] = field(
        default_factory=list
    )  # a closing order exists for these (sent now, or already sent before)
    skipped: list[str] = field(default_factory=list)  # strategies not in FLATTEN


def _epoch(oms: Oms, strategy_id: str) -> str | None:
    """When the FLATTEN now in force for this strategy was ordered (its scope or the global one), None when it is not in FLATTEN."""
    if oms.risk.switch.mode(strategy_id) is not Mode.FLATTEN:
        return None
    return max(
        e.ts
        for e in oms.risk.switch.events
        if e.mode is Mode.FLATTEN and e.scope in (None, strategy_id)
    ).isoformat()


def flatten(
    oms: Oms,
    positions: Mapping[tuple[str, int], int],
    *,
    market_of: Callable[[int], Market],
    book_of: Callable[[str, int], Book],
    day: Day,
    price_of: Callable[[int, Side], Decimal | None] = lambda _i, _s: None,
) -> FlattenReport:
    """`positions` maps (strategy_id, instrument_id) to the signed quantity held. Zero quantities are ignored. Nothing is ever closed beyond what
    the OMS's own orders bought: whatever else the account holds (shares bought by hand) is left alone even if the caller passes the broker's totals."""
    report = FlattenReport()
    own = oms.positions()
    plan: list[tuple[str, int, str, OrderRequest]] = []
    for (strategy, iid), qty in sorted(positions.items()):
        epoch = _epoch(oms, strategy)
        if epoch is None:
            if strategy not in report.skipped:
                report.skipped.append(strategy)
            continue
        if qty == 0:
            continue  # the broker says nothing is held there: there is nothing to close, whatever the OMS's own fold says
        qty = (
            min(qty, own.get((strategy, iid), 0))
            if qty > 0
            else max(qty, own.get((strategy, iid), 0))
        )
        if qty == 0:
            continue  # the OMS owns none of it (min/max above leave a quantity of the OMS's own sign, or zero)
        side = Side.SELL if qty > 0 else Side.BUY
        plan.append(
            (
                strategy,
                iid,
                f"flatten:{epoch}:{iid}",
                OrderRequest(strategy, iid, side, abs(qty), price_of(iid, side), reduce_only=True),
            )
        )
    mine = {client_order_id(s, key) for s, _, key, _ in plan}
    for strategy in sorted({s for s, *_ in plan}):
        oms.cancel_open(strategy, keep=mine)  # what the strategy had open; its closing orders stay
    for strategy, iid, key, req in plan:
        report.orders.append(oms.submit(key, req, market_of(iid), book_of(strategy, iid), day))
    return report
