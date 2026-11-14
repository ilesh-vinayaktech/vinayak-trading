# ruff: noqa: E501
"""The order lifecycle as events (spec section 11): every transition is an immutable OrderEvent and an Order is only ever
the fold of its events, so any order's full history can be replayed and the projection can never disagree with it."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from algo.risk.model import Side


class State(StrEnum):
    NEW = "NEW"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    ACKED = "ACKED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"  # the broker did not answer: the order may or may not exist there


S = State
TERMINAL = frozenset({S.FILLED, S.CANCELLED, S.REJECTED, S.EXPIRED})
OPEN = frozenset({S.SUBMITTED, S.ACKED, S.PARTIALLY_FILLED})  # live at the broker and cancellable
_LIVE = {S.ACKED, S.PARTIALLY_FILLED, *TERMINAL}
ALLOWED: dict[State, frozenset[State]] = {
    S.NEW: frozenset({S.SUBMITTING, S.REJECTED}),
    S.SUBMITTING: frozenset({S.SUBMITTED, S.REJECTED, S.UNKNOWN}),
    S.SUBMITTED: frozenset(_LIVE | {S.UNKNOWN}),
    S.ACKED: frozenset(_LIVE - {S.ACKED}),
    S.PARTIALLY_FILLED: frozenset({S.PARTIALLY_FILLED, S.FILLED, S.CANCELLED, S.EXPIRED}),
    S.UNKNOWN: frozenset({S.SUBMITTED, *_LIVE}),  # resolved by looking the order up at the broker
    S.FILLED: frozenset(),
    S.CANCELLED: frozenset(),
    S.REJECTED: frozenset(),
    S.EXPIRED: frozenset(),
}


class OrderError(Exception):
    pass


def client_order_id(strategy_id: str, intent_key: str) -> str:
    """Deterministic and broker-tag safe (letters and digits, 20 characters): the same intent always has the same id,
    so a retry after a timeout can look the order up instead of creating a second one."""
    return "A" + hashlib.sha256(f"{strategy_id}|{intent_key}".encode()).hexdigest()[:19].upper()


def is_platform_tag(tag: str) -> bool:
    """True for a tag `client_order_id` could have made. An order at the broker without one (placed by hand, or by another app) is not ours:
    the platform never cancels it, reconciles it or counts it."""
    return len(tag) == 20 and tag[0] == "A" and all(c in "0123456789ABCDEF" for c in tag[1:])


@dataclass(frozen=True)
class OrderEvent:
    order_id: str
    seq: int
    ts: datetime
    state: (
        State | None
    )  # None: a fact that does not move the state (a note, a cancel request, a reconciliation result)
    kind: str  # NEW | STATE | NOTE | CANCEL_REQUESTED | RECONCILED
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Order:
    order_id: str
    strategy_id: str
    instrument_id: int
    side: Side
    qty: int
    price: Decimal | None
    state: State = State.NEW
    filled_qty: int = 0
    avg_price: Decimal | None = None
    broker_order_id: str | None = None
    reason: str = ""
    last_seq: int = -1

    @property
    def is_open(self) -> bool:
        return self.state in OPEN

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL


def apply(order: Order | None, ev: OrderEvent) -> Order:
    """One step of the fold. Refuses a gap or repeat in the sequence and any transition the lifecycle does not allow."""
    if order is None:
        if ev.kind != "NEW" or ev.seq != 0:
            raise OrderError("an order starts with its NEW event at sequence 0")
        d = ev.data
        return Order(
            ev.order_id,
            d["strategy_id"],
            d["instrument_id"],
            Side(d["side"]),
            d["qty"],
            d["price"],
            last_seq=0,
        )
    if ev.seq != order.last_seq + 1:
        raise OrderError(f"event {ev.seq} does not follow {order.last_seq} for {order.order_id}")
    out = replace(order, last_seq=ev.seq)
    if ev.state is None:
        return out
    if ev.state not in ALLOWED[order.state]:
        raise OrderError(f"{order.order_id}: {order.state} cannot become {ev.state}")
    d = ev.data
    return replace(
        out,
        state=ev.state,
        filled_qty=d.get("filled_qty", order.filled_qty),
        avg_price=d.get("avg_price", order.avg_price),
        broker_order_id=d.get("broker_order_id", order.broker_order_id),
        reason=d.get("reason", order.reason),
    )


def replay(events: list[OrderEvent]) -> Order:
    order: Order | None = None
    for ev in events:
        order = apply(order, ev)
    if order is None:
        raise OrderError("no events")
    return order
