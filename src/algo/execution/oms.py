# ruff: noqa: E501
"""The order management system, core rules (spec section 11). The only holder of a Broker.

  * a breached order never reaches the broker (the risk engine decides first, the kill switch included)
  * a timeout makes an order UNKNOWN; it is never resubmitted blindly: the same intent looks the order up by its
    client_order_id, and an order that cannot be found pauses its strategy and raises an alert
  * broker updates are idempotent and tolerate out-of-order delivery (a duplicate, a stale fill or a late ACK is ignored)
  * every transition is an OrderEvent; `orders` is the fold of `events`
The outbox is the order log itself: SUBMITTING is the durable command, ATTEMPT marks that the send may have happened, `recover` finishes
what a crash interrupted. Not here yet: the minute reconciler process for a real broker (positions and cash from Kite). `reconciler.compare` finds
position and cash differences, `flatten.flatten` builds the closing orders."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from algo.core.clock import Clock
from algo.execution.broker import Broker, BrokerError, BrokerOrder, BrokerRejected, BrokerTimeout
from algo.execution.event_store import EventStore, MemoryStore
from algo.execution.orders import (
    ALLOWED,
    Order,
    OrderError,
    OrderEvent,
    State,
    apply,
    client_order_id,
    is_platform_tag,
    replay,
)
from algo.risk.engine import RiskEngine
from algo.risk.killswitch import Failure, FailurePolicy, Mode
from algo.risk.model import Book, Day, Market, OrderRequest, Side

STATUS = {
    "OPEN": State.ACKED,
    "PARTIAL": State.PARTIALLY_FILLED,
    "COMPLETE": State.FILLED,
    "CANCELLED": State.CANCELLED,
    "REJECTED": State.REJECTED,
    "EXPIRED": State.EXPIRED,
}


@dataclass(frozen=True)
class Mismatch:
    kind: str  # MISSING_AT_BROKER | STATE_MISMATCH | FILL_MISMATCH | ORPHAN | BROKER_UNREACHABLE
    client_order_id: str
    detail: str


class Oms:
    def __init__(
        self,
        broker: Broker,
        risk: RiskEngine,
        clock: Clock,
        policy: FailurePolicy | None = None,
        store: EventStore | None = None,
        own_positions_only: bool = False,
    ) -> None:
        self.broker, self.risk, self.clock = broker, risk, clock
        self.policy = policy or FailurePolicy()
        self.store: EventStore = store or MemoryStore()
        self.events: dict[str, list[OrderEvent]] = (
            self.store.load()
        )  # a restart replays every order
        self.orders: dict[str, Order] = {oid: replay(evs) for oid, evs in self.events.items()}
        self.own_positions_only = (
            own_positions_only  # live: never sell more than this strategy bought itself
        )
        self.alerts: list[str] = []
        self.orphans: list[BrokerOrder] = []
        self.ignored = 0

    def _emit(self, oid: str, state: State | None, kind: str = "STATE", **data: object) -> Order:
        log = self.events.setdefault(oid, [])
        ev = OrderEvent(oid, len(log), self.clock.now(), state, kind, dict(data))
        self.orders[oid] = apply(self.orders.get(oid), ev)
        self.store.append(ev)
        log.append(ev)
        return self.orders[oid]

    def submit(
        self, intent_key: str, req: OrderRequest, market: Market, book: Book, day: Day
    ) -> Order:
        oid = client_order_id(req.strategy_id, intent_key)
        existing = self.orders.get(oid)
        if existing is not None:  # the same intent again: never a second order
            return self.resolve_unknown(oid) if existing.state is State.UNKNOWN else existing
        decision = self.risk.approve(req, market, book, day, self.clock.now())
        over_sold = (
            self.own_positions_only and req.side is Side.SELL and req.qty > self._sellable(req)
        )
        self._emit(
            oid,
            None,
            "NEW",
            strategy_id=req.strategy_id,
            instrument_id=req.instrument_id,
            side=req.side.value,
            qty=req.qty,
            price=req.price,
            reduce_only=req.reduce_only,
        )
        if not decision.approved:
            return self._emit(oid, State.REJECTED, reason="risk: " + ", ".join(decision.codes))
        if over_sold:
            return self._emit(
                oid,
                State.REJECTED,
                reason="own position: more than this strategy bought (shares held from elsewhere are never sold)",
            )
        self._emit(
            oid, State.SUBMITTING
        )  # the durable command: a restart that finds it can still send it
        return self._send(oid, req)

    def _send(self, oid: str, req: OrderRequest) -> Order:
        self._emit(
            oid, None, "ATTEMPT"
        )  # written BEFORE the call: from here on the broker may have the order
        try:
            broker_id = self.broker.place_order(req, oid)
        except BrokerRejected as e:
            return self._emit(oid, State.REJECTED, reason=f"broker: {e}")
        except BrokerTimeout as e:
            return self._emit(oid, State.UNKNOWN, reason=f"no answer from the broker: {e}")
        return self._emit(oid, State.SUBMITTED, broker_order_id=broker_id)

    def recover(self) -> None:
        """Run after a restart: finish what a crash interrupted (the transactional outbox, with the order log as the outbox).
        * NEW: the risk decision never reached the log and nothing was sent: REJECTED.
        * SUBMITTING with no ATTEMPT: the command was logged but never left the process: send it, unless the strategy is paused now.
        * SUBMITTING with an ATTEMPT: the broker may have it: UNKNOWN, found by its tag or escalated, never resent."""
        for oid, o in list(self.orders.items()):
            if o.state is State.NEW:
                self._emit(
                    oid,
                    State.REJECTED,
                    reason="interrupted before it was decided; nothing was sent",
                )
            elif o.state is State.SUBMITTING:
                if any(e.kind == "ATTEMPT" for e in self.events[oid]):
                    self._emit(
                        oid, State.UNKNOWN, reason="the process stopped while it was being sent"
                    )
                    self.resolve_unknown(oid)
                    continue
                new = self.events[oid][0].data
                req = OrderRequest(
                    o.strategy_id,
                    o.instrument_id,
                    o.side,
                    o.qty,
                    o.price,
                    new.get("reduce_only", False),
                )
                mode = self.risk.switch.mode(o.strategy_id)
                if mode.blocks_new and not (req.reduce_only and mode is Mode.FLATTEN):
                    self._emit(
                        oid,
                        State.REJECTED,
                        reason=f"the kill switch is {mode.value}: not sent after the restart",
                    )
                else:
                    self._send(oid, req)

    def on_update(self, u: BrokerOrder) -> Order | None:
        """A broker update (postback, stream or poll). Returns the order when it changed, None when it was ignored."""
        o = self.orders.get(u.client_order_id)
        if o is None:
            self.orphans.append(u)
            return None
        target = STATUS.get(u.status)
        if target is None:
            raise OrderError(f"unknown broker status {u.status!r}")
        stale = o.is_terminal or u.filled_qty < o.filled_qty
        duplicate = target is o.state and u.filled_qty == o.filled_qty
        if stale or duplicate or target not in ALLOWED[o.state]:
            self.ignored += 1
            return None
        extra = {"reason": u.reason} if u.reason else {}
        return self._emit(
            o.order_id,
            target,
            filled_qty=u.filled_qty,
            avg_price=u.avg_price,
            broker_order_id=u.broker_order_id,
            **extra,
        )

    def adopt(self, intent_key: str, req: OrderRequest, sent: BrokerOrder) -> Order:
        """Record an order that was already sent to the broker (before the OMS kept this log) without sending anything: it enters
        as NEW, SUBMITTING, SUBMITTED and is then brought to the broker's current state."""
        oid = client_order_id(req.strategy_id, intent_key)
        if sent.client_order_id != oid:
            raise OrderError(
                f"the broker order {sent.client_order_id} is not the tag {oid} this intent would have sent"
            )
        if oid in self.orders:
            return self.orders[oid]
        self._emit(
            oid,
            None,
            "NEW",
            strategy_id=req.strategy_id,
            instrument_id=req.instrument_id,
            side=req.side.value,
            qty=req.qty,
            price=req.price,
            reduce_only=req.reduce_only,
        )
        self._emit(oid, State.SUBMITTING)
        self._emit(oid, State.SUBMITTED, broker_order_id=sent.broker_order_id)
        self.on_update(sent)
        return self.orders[oid]

    def _escalate(self, o: Order, why: str) -> Order:
        self._emit(o.order_id, None, "NOTE", text=why)
        mode = self.risk.switch.apply(
            Failure.AMBIGUOUS_ORDER, self.policy, o.strategy_id, self.clock.now()
        )
        self.alerts.append(
            f"order {o.order_id} is UNKNOWN ({why}); {o.strategy_id} is now {mode.value}"
        )
        return self.orders[o.order_id]

    def resolve_unknown(self, order_id: str) -> Order:
        o = self.orders[order_id]
        if o.state is not State.UNKNOWN:
            return o
        try:
            found = next((b for b in self.broker.orders() if b.client_order_id == order_id), None)
        except BrokerError as e:
            return self._escalate(o, f"the lookup failed: {e}")
        if found is None:
            return self._escalate(o, "not found at the broker")
        self.on_update(found)
        return self.orders[order_id]

    def confirm_not_sent(self, order_id: str, *, by: str, reason: str) -> Order:
        """A person has checked that the broker never had the order: the only way an UNKNOWN order ends without the broker's word."""
        o = self.orders[order_id]
        if o.state is not State.UNKNOWN:
            raise OrderError(f"{order_id} is {o.state}, not UNKNOWN")
        return self._emit(order_id, State.CANCELLED, reason=f"confirmed not sent by {by}: {reason}")

    def _sellable(self, req: OrderRequest) -> int:
        """What this strategy may still sell of the instrument: what it bought, less what it already has selling."""
        held = self.positions().get((req.strategy_id, req.instrument_id), 0)
        selling = sum(
            o.qty - o.filled_qty
            for o in self.orders.values()
            if o.side is Side.SELL
            and (o.strategy_id, o.instrument_id) == (req.strategy_id, req.instrument_id)
            and (o.is_open or o.state in (State.SUBMITTING, State.UNKNOWN))
        )
        return held - selling

    def positions(self) -> dict[tuple[str, int], int]:
        """What the OMS's own orders add up to: signed filled quantity per (strategy, instrument), zero ones left out."""
        out: dict[tuple[str, int], int] = {}
        for o in self.orders.values():
            key = (o.strategy_id, o.instrument_id)
            out[key] = out.get(key, 0) + o.side.sign * o.filled_qty
        return {k: q for k, q in out.items() if q != 0}

    def cancel_open(self, scope: str | None = None, keep: Collection[str] = ()) -> list[str]:
        """Ask the broker to cancel open orders (one strategy, or all), except the order ids in `keep`. The order becomes CANCELLED when the broker says so."""
        requested = []
        for o in list(self.orders.values()):
            if o.is_open and o.order_id not in keep and (scope is None or o.strategy_id == scope):
                try:
                    self.broker.cancel_order(o.broker_order_id or "")
                except BrokerError as e:
                    self._emit(o.order_id, None, "NOTE", text=f"cancel failed: {e}")
                    continue
                self._emit(o.order_id, None, "CANCEL_REQUESTED")
                requested.append(o.order_id)
        return requested

    def reconcile(self, threshold: int = 1, extra: Sequence[Mismatch] = ()) -> list[Mismatch]:
        """Compare the OMS with the broker (the broker is the truth). `extra` are differences found elsewhere (positions, cash: see reconciler.compare) and count the same. At `threshold` mismatches trading is paused and an alert raised."""
        now = self.clock.now()
        try:
            remote = {b.client_order_id: b for b in self.broker.orders()}
        except BrokerError as e:
            self.risk.switch.apply(Failure.BROKER_DOWN, self.policy, None, now)
            self.alerts.append(f"reconciliation could not read the broker: {e}")
            return [Mismatch("BROKER_UNREACHABLE", "", str(e))]
        out: list[Mismatch] = []
        for oid, o in self.orders.items():
            if o.state in (State.NEW, State.REJECTED):
                continue  # never reached the broker
            b = remote.get(oid)
            if b is None:
                out.append(
                    Mismatch(
                        "MISSING_AT_BROKER",
                        oid,
                        f"the OMS has it {o.state}, the broker does not know it",
                    )
                )
            elif not (
                STATUS.get(b.status) is o.state
                or (STATUS.get(b.status) is State.ACKED and o.state is State.SUBMITTED)
            ):  # OPEN at the broker is a submitted order that has not had its first update yet
                out.append(
                    Mismatch("STATE_MISMATCH", oid, f"the OMS has {o.state}, the broker {b.status}")
                )
            elif b.filled_qty != o.filled_qty:
                out.append(
                    Mismatch(
                        "FILL_MISMATCH",
                        oid,
                        f"the OMS filled {o.filled_qty}, the broker {b.filled_qty}",
                    )
                )
        out += list(extra)
        out += [
            Mismatch("ORPHAN", c, "the broker has an order the OMS never sent")
            for c in remote
            if c not in self.orders
            and is_platform_tag(c)  # an order placed by hand is not ours to reconcile
        ]
        for m in out:
            if m.client_order_id in self.orders:
                self._emit(m.client_order_id, None, "RECONCILED", result=m.kind, detail=m.detail)
        if len(out) >= threshold:
            self.risk.switch.apply(Failure.RECONCILIATION, self.policy, None, now)
            self.alerts.append(
                f"reconciliation found {len(out)} mismatch(es): " + "; ".join(m.kind for m in out)
            )
        return out
