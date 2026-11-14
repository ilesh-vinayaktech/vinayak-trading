# ruff: noqa: E501
"""The paper path on the OMS. Approving an order sends it through the OMS (risk first) to a PaperBroker, which is the paper order
table seen as a broker's order book: an approved order is OPEN, a fill is COMPLETE, a refused fill is REJECTED, a cancellation by the
kill switch or the OMS is CANCELLED, an order that expired unfilled is EXPIRED. The existing simulated fill (`orders.fill_due`) is the
matching engine; after it runs, `sync` hands what changed to the OMS as broker updates. The OMS log (`oms_event`) is the persistent
record and `reconcile` compares it with the order table. The OMS replays its whole log on every build: fine for paper volumes,
a cache is due before it grows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg

from algo.core.clock import SimClock
from algo.execution.broker import BrokerError, BrokerOrder, BrokerRejected
from algo.execution.event_store import DbStore
from algo.execution.oms import Mismatch, Oms
from algo.execution.orders import Order, client_order_id
from algo.paper import risk as paper_risk
from algo.risk import store as kill_switch
from algo.risk.engine import RiskEngine
from algo.risk.limits import Limits
from algo.risk.model import OrderRequest, Side


@dataclass(frozen=True)
class _Row:
    order_id: UUID
    user_id: UUID
    strategy_id: str
    instrument_id: int
    side: str
    qty: Decimal
    status: str
    fill_price: Decimal | None
    failure: str | None

    @property
    def client_order_id(self) -> str:
        return client_order_id(self.strategy_id, str(self.order_id))

    def request(self) -> OrderRequest:
        return OrderRequest(self.strategy_id, self.instrument_id, Side(self.side), int(self.qty))

    def as_broker_order(self) -> BrokerOrder:
        if self.status == "APPROVED":
            return BrokerOrder(str(self.order_id), self.client_order_id, "OPEN")
        if self.status == "FILLED":
            return BrokerOrder(
                str(self.order_id), self.client_order_id, "COMPLETE", int(self.qty), self.fill_price
            )
        why = self.failure or ""
        if why.startswith("cancelled"):
            return BrokerOrder(str(self.order_id), self.client_order_id, "CANCELLED", reason=why)
        if why.startswith("not filled before"):
            return BrokerOrder(str(self.order_id), self.client_order_id, "EXPIRED", reason=why)
        return BrokerOrder(str(self.order_id), self.client_order_id, "REJECTED", reason=why)


def _rows(conn: psycopg.Connection) -> list[_Row]:
    """Every order that was sent: answered by its owner with an approval (a rejected or unanswered order never reached the broker)."""
    return [
        _Row(*r)
        for r in conn.execute(
            "SELECT o.order_id, o.user_id, a.strategy_id, o.instrument_id, o.side, o.qty, o.status, o.fill_price, o.failure"
            " FROM paper_order o JOIN paper_account a USING (user_id)"
            " WHERE o.decided_at IS NOT NULL AND o.status <> 'REJECTED' ORDER BY o.created_at, o.order_id"
        )
    ]


class PaperBroker:
    """The paper order table as a broker. Send an order by `expect`ing its tag and then `place_order` (the OMS does the second)."""

    def __init__(self, conn: psycopg.Connection, now: datetime) -> None:
        self.conn, self.now = conn, now
        self._expected: dict[str, tuple[UUID, UUID]] = {}

    def expect(self, client_tag: str, order_id: UUID, user_id: UUID) -> None:
        self._expected[client_tag] = (order_id, user_id)

    def place_order(self, req: Any, client_order_id: str) -> str:
        if client_order_id not in self._expected:
            raise BrokerRejected("this order is not pending")
        order_id, user_id = self._expected.pop(client_order_id)
        sent = self.conn.execute(
            "UPDATE paper_order SET status='APPROVED', decided_at=%s, decided_by=%s WHERE order_id=%s AND status='PENDING'",
            (self.now, user_id, order_id),
        ).rowcount
        if not sent:
            raise BrokerRejected("this order is not pending")
        return str(order_id)

    def cancel_order(self, broker_order_id: str) -> None:
        done = self.conn.execute(
            "UPDATE paper_order SET status='FAILED', failure='cancelled by the OMS' WHERE order_id=%s AND status='APPROVED'",
            (broker_order_id,),
        ).rowcount
        if not done:
            raise BrokerError("this order is not open")

    def orders(self) -> list[BrokerOrder]:
        return [r.as_broker_order() for r in _rows(self.conn)]


def build(conn: psycopg.Connection, now: datetime, *, limits: Limits | None = None) -> Oms:
    broker = PaperBroker(conn, now)
    oms = Oms(
        broker,
        RiskEngine(limits or Limits(), kill_switch.load(conn)),
        SimClock(now),
        store=DbStore(conn),
    )
    return oms


def submit_approved(
    conn: psycopg.Connection, user_id: UUID, order_id: UUID, now: datetime
) -> Order:
    """Approval: the order goes through the OMS (risk again, then the broker). The caller has already shown the owner any risk refusal."""
    request, market, state, day = paper_risk.inputs(conn, user_id, order_id, now)
    oms = build(conn, now, limits=paper_risk.get_limits(conn, user_id))
    broker = oms.broker
    assert isinstance(broker, PaperBroker)
    broker.expect(client_order_id(request.strategy_id, str(order_id)), order_id, user_id)
    return oms.submit(str(order_id), request, market, state, day)


def sync(conn: psycopg.Connection, now: datetime) -> Oms:
    """Hand what happened to the paper orders (fills, refusals, cancellations, expiries) to the OMS as broker updates, adopting any
    order approved before the OMS kept a log."""
    oms = build(conn, now)
    for row in _rows(conn):
        sent = row.as_broker_order()
        if row.client_order_id in oms.orders:
            oms.on_update(sent)
        else:
            oms.adopt(str(row.order_id), row.request(), sent)
    return oms


def reconcile(conn: psycopg.Connection, now: datetime) -> list[Mismatch]:
    return build(conn, now).reconcile()
