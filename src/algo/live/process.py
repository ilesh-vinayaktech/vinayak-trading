# ruff: noqa: E501
"""The live process (docs: TODO 5.3): the loop that runs what was only ever called by tests.
  * `start`: finish what a crash interrupted (`Oms.recover`), then say RUNNING.
  * `tick` (call it every few seconds): take the kill-switch state from the database (a pause from the portal reaches a running process), reconcile
    the OMS with the Kite account once a minute in session and once after the close, save any pause the reconciler caused, and beat.
The broker, the account reader and the gate are built by the caller (scripts/live_process.py); nothing here talks to the network itself."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import psycopg

from algo.backtest.costs.policy import CostPolicy
from algo.core.clock import Clock
from algo.execution.broker import BrokerError
from algo.execution.live_reconcile import AccountReader, reconcile_live
from algo.execution.oms import Mismatch, Oms
from algo.execution.orders import State, client_order_id
from algo.live import heartbeat, market_calendar
from algo.paper import book as paper_book
from algo.paper import orders as paper_orders
from algo.paper import risk as paper_risk
from algo.risk import store as risk_store

PROCESS = "live"
EVERY = timedelta(seconds=60)


class LiveProcess:
    def __init__(
        self,
        oms: Oms,
        reader: AccountReader,
        symbols: dict[int, str],
        clock: Clock,
        conn: psycopg.Connection,
        *,
        host: str,
        pid: int,
        cost: CostPolicy | None = None,
    ) -> None:
        self.oms, self.reader, self.symbols, self.clock, self.conn = (
            oms,
            reader,
            symbols,
            clock,
            conn,
        )
        self.host, self.pid, self.cost = host, pid, cost
        self._last: datetime | None = None
        self._final_done: date | None = None
        self._saved = 0  # switch events already in the database
        self._cancel_asked: set[str] = set()  # orders the broker was already asked to cancel

    def _beat(self, state: str, detail: str) -> None:
        heartbeat.beat(
            self.conn, PROCESS, state, detail, self.clock.now(), pid=self.pid, host=self.host
        )

    def _flush(self) -> None:
        """Write the pauses the OMS made in memory (an unresolved order, a reconciliation mismatch) so a restart stays paused."""
        sw = self.oms.risk.switch
        risk_store.save_new(self.conn, sw, self._saved)
        self._saved = len(sw.events)

    def _sync(self) -> None:
        """Keep our own pauses, then take what the portal changed."""
        self._flush()
        self.oms.risk.switch = risk_store.load(self.conn)
        self._saved = len(self.oms.risk.switch.events)

    def _cancel_open(self) -> None:
        """CANCEL and FLATTEN mean the open orders come off the broker, once each (a failed cancel is asked again next tick)."""
        sw = self.oms.risk.switch
        for strategy in {o.strategy_id for o in self.oms.orders.values() if o.is_open}:
            if sw.mode(strategy).cancels_open:
                self._cancel_asked.update(self.oms.cancel_open(strategy, keep=self._cancel_asked))

    def _fail(self, order_id: UUID, why: str) -> None:
        self.conn.execute(
            "UPDATE paper_order SET status='FAILED', failure=%s WHERE order_id=%s AND status='APPROVED'",
            (why[:300], order_id),
        )

    def _send_approved(self) -> None:
        """Orders an owner approved on a LIVE account go through this process's OMS (risk again, then the broker), once each. One that ran out
        of time before it was sent is failed, never sent late at a stale price."""
        now = self.clock.now()
        rows = self.conn.execute(
            "SELECT o.order_id, o.user_id, o.expires_at, a.strategy_id FROM paper_order o JOIN paper_account a USING (user_id)"
            " WHERE a.mode='LIVE' AND o.status='APPROVED' ORDER BY o.decided_at, o.order_id"
        ).fetchall()
        for oid, uid, expires, strategy in rows:
            if client_order_id(strategy, str(oid)) in self.oms.orders:
                continue  # already sent: the broker's updates take it from here
            if now >= expires:
                self._fail(oid, "expired before the live process sent it")
                continue
            request, market, state, day = paper_risk.inputs(self.conn, uid, oid, now)
            sent = self.oms.submit(str(oid), request, market, state, day)
            if sent.state is State.REJECTED:
                self._fail(oid, sent.reason)

    def _book(self, uid: UUID, oid: UUID, strategy: str) -> None:
        """What the broker filled of this order and has not been booked yet goes into the account's book (the same one paper fills go to), once,
        at the price the broker's running average implies for the new shares; then the order says how it ended."""
        o = self.oms.orders[client_order_id(strategy, str(oid))]
        booked = self.conn.execute(
            "SELECT coalesce(sum(qty), 0), coalesce(sum(qty * price), 0) FROM paper_event WHERE user_id=%s AND ref LIKE %s",
            (uid, f"live:{oid}:%"),
        ).fetchone()
        assert booked is not None  # an aggregate always returns a row
        done, spent = booked
        new = Decimal(o.filled_qty) - done
        if new > 0 and o.avg_price is not None:
            day = self.clock.now().astimezone(market_calendar.IST).date()
            price = (o.avg_price * o.filled_qty - spent) / new
            side = o.side.value
            iid = o.instrument_id
            ch = (
                self.cost.charges(
                    day,
                    side,
                    new,
                    price,
                    dp_already_charged=side == "SELL"
                    and paper_orders._dp_charged(self.conn, uid, iid, day),  # noqa: SLF001
                )
                if self.cost is not None
                else None
            )
            paper_book.record_fill(
                self.conn,
                uid,
                day=day,
                side=side,
                iid=iid,
                qty=new,
                price=price,
                commission=ch.amount("COMMISSION") if ch else Decimal(0),
                charges=[(ln.type, ln.amount) for ln in ch.lines if ln.type != "COMMISSION"]
                if ch
                else [],
                ref=f"live:{oid}:{o.filled_qty}",
                now=self.clock.now(),
                enforce=False,
            )
        if o.state is State.FILLED:
            self.conn.execute(
                "UPDATE paper_order SET status='FILLED', fill_day=%s, fill_price=%s, filled_at=%s WHERE order_id=%s AND status='APPROVED'",
                (
                    self.clock.now().astimezone(market_calendar.IST).date(),
                    o.avg_price,
                    self.clock.now(),
                    oid,
                ),
            )
        elif o.is_terminal:
            why = o.reason or o.state.value.lower()
            note = f"{why}" if not o.filled_qty else f"{why} after {o.filled_qty} of {o.qty} filled"
            self._fail(oid, note)

    def _settle(self) -> None:
        """Take the broker's word on our open orders, then book what filled. A broker that cannot be read is left to the reconciler (it halts)."""
        if any(o.is_open for o in self.oms.orders.values()):
            try:
                remote = self.oms.broker.orders()
            except BrokerError:
                remote = []
            for b in remote:
                if b.client_order_id in self.oms.orders:
                    self.oms.on_update(b)
        rows = self.conn.execute(
            "SELECT o.order_id, o.user_id, a.strategy_id FROM paper_order o JOIN paper_account a USING (user_id) WHERE a.mode='LIVE' AND o.status='APPROVED'"
        ).fetchall()
        for oid, uid, strategy in rows:
            if client_order_id(strategy, str(oid)) in self.oms.orders:
                self._book(uid, oid, strategy)

    def start(self) -> None:
        self._beat("STARTING", "recovering the order log")
        self._sync()
        self.oms.recover()
        self._flush()
        self._beat("RUNNING", "recovered")

    def stop(self) -> None:
        self._beat("STOPPED", "stopped")

    def _due(self, now: datetime) -> bool:
        """A minute has passed in session, or the session is over and today's final pass has not run."""
        day = now.astimezone(market_calendar.IST).date()
        windows = market_calendar.windows_for(self.conn, day)
        if any(s <= now < e for s, e in windows):
            return self._last is None or now - self._last >= EVERY
        if windows and now >= windows[-1][1] and self._final_done != day:
            self._final_done = day
            return True
        return False

    def tick(self) -> list[Mismatch]:
        now = self.clock.now()
        self._sync()  # the portal's pause, cancel, resume or flatten
        self._cancel_open()
        self._send_approved()
        self._settle()
        found: list[Mismatch] = []
        if self._due(now):
            self._last = now
            found = reconcile_live(self.oms, self.reader, self.symbols)
        self._flush()
        if found:
            self._beat("DEGRADED", "; ".join(sorted({m.kind for m in found})))
        else:
            self._beat("RUNNING", "")
        return found
