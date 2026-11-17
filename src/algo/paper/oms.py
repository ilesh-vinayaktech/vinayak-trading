# ruff: noqa: E501
"""The paper path on the OMS. Approving an order sends it through the OMS (risk first) to a PaperBroker, which is the paper order
table seen as a broker's order book: an approved order is OPEN, a fill is COMPLETE, a refused fill is REJECTED, a cancellation by the
kill switch or the OMS is CANCELLED, an order that expired unfilled is EXPIRED. The existing simulated fill (`orders.fill_due`) is the
matching engine; after it runs, `sync` hands what changed to the OMS as broker updates. The OMS log (`oms_event`) is the persistent
record and `reconcile` compares it with the order table. The OMS replays its whole log on every build: fine for paper volumes,
a cache is due before it grows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid5

import psycopg

from algo.core.clock import SimClock
from algo.execution.broker import BrokerError, BrokerOrder, BrokerRejected
from algo.execution.event_store import DbStore
from algo.execution.oms import Mismatch, Oms
from algo.execution.orders import Order, client_order_id
from algo.execution.reconciler import Portfolio, compare
from algo.paper import book
from algo.paper import risk as paper_risk
from algo.risk import store as kill_switch
from algo.risk.engine import RiskEngine
from algo.risk.killswitch import Mode
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
    limit_price: Decimal | None

    @property
    def client_order_id(self) -> str:
        return client_order_id(self.strategy_id, str(self.order_id))

    def request(self) -> OrderRequest:
        return OrderRequest(
            self.strategy_id, self.instrument_id, Side(self.side), int(self.qty), self.limit_price
        )

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
            "SELECT o.order_id, o.user_id, a.strategy_id, o.instrument_id, o.side, o.qty, o.status, o.fill_price, o.failure, o.limit_price"
            " FROM paper_order o JOIN paper_account a USING (user_id)"
            " WHERE o.decided_at IS NOT NULL AND o.status <> 'REJECTED' AND a.mode='PAPER' ORDER BY o.created_at, o.order_id"
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
            "UPDATE paper_order SET status='APPROVED', decided_at=%s, decided_by=(SELECT owner_user_id FROM paper_account WHERE user_id=%s) WHERE order_id=%s AND status='PENDING'",
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


def position_mismatches(conn: psycopg.Connection) -> list[Mismatch]:
    """Per account, what its FILLED orders add up to against what the paper book recorded as bought and sold. Two records of the same
    fills that only agree when every fill was booked exactly once (splits change the ledger's holdings, so those are not compared)."""
    out: list[Mismatch] = []
    for (user_id,) in conn.execute(
        "SELECT user_id FROM paper_account WHERE mode='PAPER' ORDER BY user_id"
    ).fetchall():
        orders = {
            int(i): int(q)
            for i, q in conn.execute(
                "SELECT instrument_id, sum(CASE side WHEN 'BUY' THEN qty ELSE -qty END) FROM paper_order"
                " WHERE user_id=%s AND status='FILLED' GROUP BY instrument_id",
                (user_id,),
            )
        }
        booked = {
            int(i): int(q)
            for i, q in conn.execute(
                "SELECT instrument_id, sum(CASE kind WHEN 'BUY' THEN qty ELSE -qty END) FROM paper_event"
                " WHERE user_id=%s AND kind IN ('BUY', 'SELL') GROUP BY instrument_id",
                (user_id,),
            )
        }
        out += [
            Mismatch(m.kind, m.client_order_id, f"account {user_id}: {m.detail}")
            for m in compare(Portfolio(orders), Portfolio(booked))
        ]
    return out


def reconcile(conn: psycopg.Connection, now: datetime) -> list[Mismatch]:
    """Orders and positions against the paper book. A mismatch pauses the strategy, and that pause is saved (it is a halt, not a note)."""
    oms = build(conn, now)
    known = len(oms.risk.switch.events)
    found = oms.reconcile(extra=position_mismatches(conn))
    kill_switch.save_new(conn, oms.risk.switch, known)
    return found


FLATTEN_REASON = "flatten"  # the reason prefix of a closing order: the kill switch's own cancellation leaves these alone
FLATTEN_LIFE = timedelta(
    days=4
)  # a closing order waits this long for a live price (covers a weekend)
_FLATTEN_NS = UUID("6f1a2f3e-5b7c-4d8e-9a0b-1c2d3e4f5a6b")


@dataclass(frozen=True)
class FlattenResult:
    sent: list[UUID]
    refused: list[tuple[UUID, int, str]]  # (user, instrument, why): tried again on the next run


def _last_close(conn: psycopg.Connection, instrument_id: int) -> Decimal | None:
    row = conn.execute(
        "SELECT close FROM bar_1d WHERE instrument_id=%s ORDER BY ts DESC, dataset_version DESC LIMIT 1",
        (instrument_id,),
    ).fetchone()
    return None if row is None else Decimal(row[0])


def flatten(conn: psycopg.Connection, now: datetime) -> FlattenResult:
    """Close every position of each account whose kill switch is FLATTEN, with a market sell approved by the operator's FLATTEN itself
    (it needed an explicit emergency override), through the OMS and the risk engine. Safe to repeat: a closing order's id comes from the
    FLATTEN event, the account and the stock, so the same FLATTEN never creates a second one; a later FLATTEN closes what was bought since."""
    switch = kill_switch.load(conn)
    sent: list[UUID] = []
    refused: list[tuple[UUID, int, str]] = []
    for user_id, strategy, mode in conn.execute(
        "SELECT user_id, strategy_id, mode FROM paper_account ORDER BY user_id"
    ).fetchall():
        if switch.mode(strategy) is not Mode.FLATTEN:
            continue
        ordered = max(
            (e for e in switch.events if e.mode is Mode.FLATTEN and e.scope in (None, strategy)),
            key=lambda e: e.ts,
        )  # the FLATTEN now in force
        epoch = ordered.ts
        for iid, qty in sorted(book.load(conn, user_id).quantities().items()):
            ref = _last_close(conn, iid) if qty > 0 else None
            if ref is None:
                if qty > 0:
                    refused.append((user_id, iid, "no price known to value the order"))
                continue
            oid = uuid5(_FLATTEN_NS, f"{user_id}|{epoch.isoformat()}|{iid}")
            made = conn.execute(
                "INSERT INTO paper_order (order_id, user_id, decision_day, instrument_id, side, qty, ref_price, reason, created_at, not_before, expires_at)"
                " VALUES (%s,%s,%s,%s,'SELL',%s,%s,%s,%s,%s,%s) ON CONFLICT (order_id) DO NOTHING",
                (
                    oid, user_id, now.date(), iid, qty, ref,
                    f"{FLATTEN_REASON}: {ordered.reason}"[:200],
                    now, now, now + FLATTEN_LIFE,
                ),
            ).rowcount  # fmt: skip
            if not made:
                continue  # already sent for this FLATTEN
            decision = paper_risk.check_approval(conn, user_id, oid, now)
            if not decision.approved:  # not sent: take the row back so the next run tries again
                conn.execute("DELETE FROM paper_order WHERE order_id=%s", (oid,))
                refused.append((user_id, iid, ", ".join(decision.codes)))
                continue
            if (
                mode == "LIVE"
            ):  # the one place the venues part: approved by the FLATTEN itself, sent by the live process
                conn.execute(
                    "UPDATE paper_order SET status='APPROVED', decided_at=%s, decided_by=(SELECT owner_user_id FROM paper_account WHERE user_id=%s)"
                    " WHERE order_id=%s AND status='PENDING'",
                    (now, user_id, oid),
                )
                sent.append(oid)
                continue
            sent_order = submit_approved(conn, user_id, oid, now)
            if sent_order.is_terminal:
                conn.execute(
                    "UPDATE paper_order SET status='FAILED', failure=%s WHERE order_id=%s AND status='PENDING'",
                    (sent_order.reason, oid),
                )
                refused.append((user_id, iid, sent_order.reason))
            else:
                sent.append(oid)
    return FlattenResult(sent, refused)
