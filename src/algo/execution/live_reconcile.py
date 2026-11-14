# ruff: noqa: E501
"""The live reconciler (spec section 11): the OMS's own fills against what the real Kite account holds, run every minute in market hours and
once after the close by the live process. Orders are compared by `Oms.reconcile`; this adds the positions.
  * the broker is the truth, but it also holds what the owner bought by hand: MORE at the broker than we bought is expected, LESS is a mismatch
  * holdings are read as settled + unsettled (T+1) quantity; day positions are not added, because a delivery buy of today shows in both lists
    and would be counted twice (to be checked against a real order on the first live day)
  * a stock with no Kite symbol in `symbols` is not ours and is ignored; cash is not compared (it moves with the owner's own trades)
  * an account that cannot be read halts trading, the same as an order list that cannot be read"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from algo.execution.broker import BrokerError
from algo.execution.kite_account import Account
from algo.execution.oms import Mismatch, Oms
from algo.execution.reconciler import Portfolio, compare


class AccountReader(Protocol):
    def read(self) -> Account: ...


def reconcile_live(oms: Oms, reader: AccountReader, symbols: Mapping[int, str]) -> list[Mismatch]:
    """`symbols` maps instrument id to Kite trading symbol (the one the KiteBroker sends orders with)."""
    try:
        account = reader.read()
    except BrokerError as e:
        return oms.reconcile(
            extra=[Mismatch("BROKER_UNREACHABLE", "", f"the account could not be read: {e}")]
        )
    held: dict[str, int] = {}
    for h in account.holdings:
        held[h.symbol] = held.get(h.symbol, 0) + h.total
    by_symbol = {s: i for i, s in symbols.items()}
    theirs = {by_symbol[s]: q for s, q in held.items() if s in by_symbol and q}
    ours: dict[int, int] = {}
    for (_, iid), q in oms.positions().items():
        ours[iid] = ours.get(iid, 0) + q
    diff = compare(Portfolio(ours), Portfolio(theirs), broker_may_hold_more=True)
    return oms.reconcile(extra=diff)
