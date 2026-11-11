# ruff: noqa: E501
"""A paper order's life after the runner proposes it: its owner approves or rejects it, and an approved one fills.

Only the owner can answer an order (someone else's id looks like it does not exist), once, and not after it expired or
while the account is paused. A simulated fill happens at the OPEN of the first live 1-minute bar at or after both the start
of the order's session and the approval (rounded up to the next minute): a pre-open approval fills at the session's
first open, a mid-session one at the next minute's open, never at a price that has already gone. Slippage and charges come
from the injected cost policy; the fill is booked in the paper book (which refuses what the account cannot afford or hold,
failing the order with the reason). An approved order with no price before its session ends fails; an unanswered one expires.
UNVALIDATED research: nothing here places a real order."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg
from psycopg.types.json import Jsonb

from algo.backtest.costs.policy import CostPolicy
from algo.backtest.costs.slippage import fill_price
from algo.paper import book

IST = ZoneInfo("Asia/Kolkata")
COLUMNS = (
    "o.order_id, o.user_id, o.decision_day, o.instrument_id, i.symbol, o.side, o.qty, o.ref_price, o.reason, o.status,"
    " o.created_at, o.not_before, o.expires_at, o.decided_at, o.fill_day, o.fill_price, o.fill_commission, o.filled_at, o.failure"
)
KEYS = [c.split(".")[1] for c in COLUMNS.replace(" ", "").split(",")]


class OrderError(ValueError):
    pass


@dataclass(frozen=True)
class FillReport:
    filled: int
    failed: int
    waiting: int  # approved, but no live price yet (or the account is paused)


def list_orders(
    conn: psycopg.Connection, user_id: UUID, *, statuses: list[str] | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    sql = f"SELECT {COLUMNS} FROM paper_order o JOIN instrument i USING (instrument_id) WHERE o.user_id=%s"
    args: list[Any] = [user_id]
    if statuses:
        sql += " AND o.status = ANY(%s)"
        args.append(statuses)
    rows = conn.execute(
        sql + " ORDER BY o.created_at DESC, o.order_id LIMIT %s", (*args, limit)
    ).fetchall()
    return [dict(zip(KEYS, r, strict=True)) for r in rows]


def get_order(conn: psycopg.Connection, order_id: UUID, *, user_id: UUID) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {COLUMNS} FROM paper_order o JOIN instrument i USING (instrument_id) WHERE o.order_id=%s AND o.user_id=%s",
        (order_id, user_id),
    ).fetchone()
    return None if row is None else dict(zip(KEYS, row, strict=True))


def _answerable(conn: psycopg.Connection, order_id: UUID, user_id: UUID, now: datetime) -> None:
    row = conn.execute(
        "SELECT status, expires_at FROM paper_order WHERE order_id=%s AND user_id=%s FOR UPDATE",
        (order_id, user_id),
    ).fetchone()
    if row is None:
        raise OrderError("no such order")
    if row[0] != "PENDING":
        raise OrderError(f"this order is already {row[0].lower()}")
    if now >= row[1]:
        conn.execute("UPDATE paper_order SET status='EXPIRED' WHERE order_id=%s", (order_id,))
        raise OrderError("this order has expired")


def _decide(
    conn: psycopg.Connection, order_id: UUID, user_id: UUID, now: datetime, status: str
) -> None:
    conn.execute(
        "UPDATE paper_order SET status=%s, decided_at=%s, decided_by=%s WHERE order_id=%s",
        (status, now, user_id, order_id),
    )


def approve(conn: psycopg.Connection, order_id: UUID, *, user_id: UUID, now: datetime) -> None:
    _answerable(conn, order_id, user_id, now)
    acct = book.get_account(conn, user_id)
    if acct is None or not acct["enabled"] or acct["attention"]:
        raise OrderError("the account is paused, so orders cannot be approved")
    _decide(conn, order_id, user_id, now, "APPROVED")


def reject(conn: psycopg.Connection, order_id: UUID, *, user_id: UUID, now: datetime) -> None:
    _answerable(conn, order_id, user_id, now)
    _decide(conn, order_id, user_id, now, "REJECTED")


def expire_due(conn: psycopg.Connection, now: datetime) -> tuple[int, int]:
    """(unanswered orders expired, approved orders that never found a price failed)."""
    expired = conn.execute(
        "UPDATE paper_order SET status='EXPIRED' WHERE status='PENDING' AND expires_at <= %s",
        (now,),
    ).rowcount
    failed = conn.execute(
        "UPDATE paper_order SET status='FAILED', failure='not filled before the order expired' WHERE status='APPROVED' AND expires_at <= %s",
        (now,),
    ).rowcount
    return expired, failed


def _next_minute(t: datetime) -> datetime:
    return (
        t
        if t.second == 0 and t.microsecond == 0
        else t.replace(second=0, microsecond=0) + timedelta(minutes=1)
    )


def fill_due(
    conn: psycopg.Connection, now: datetime, *, cost: CostPolicy, slippage_bps: Decimal
) -> FillReport:
    filled = failed = waiting = 0
    due = conn.execute(
        "SELECT order_id, user_id, instrument_id, side, qty, not_before, expires_at, decided_at FROM paper_order WHERE status='APPROVED' AND expires_at > %s ORDER BY created_at, order_id",
        (now,),
    ).fetchall()
    for order_id, user_id, iid, side, qty, not_before, expires_at, decided_at in due:
        acct = book.get_account(conn, user_id)
        bar = conn.execute(
            "SELECT ts, open FROM live_bar_1m WHERE instrument_id=%s AND ts >= %s AND ts < %s ORDER BY ts LIMIT 1",
            (iid, max(not_before, _next_minute(decided_at)), expires_at),
        ).fetchone()
        if acct is None or not acct["enabled"] or acct["attention"] or bar is None:
            waiting += 1
            continue
        day = bar[0].astimezone(IST).date()
        price = fill_price(bar[1], side, slippage_bps)
        ch = cost.charges(day, side, qty, price)
        extra = [(ln.type, ln.amount) for ln in ch.lines if ln.type != "COMMISSION"]
        try:
            book.record_fill(
                conn,
                user_id,
                day=day,
                side=side,
                iid=iid,
                qty=qty,
                price=price,
                commission=ch.amount("COMMISSION"),
                charges=extra,
                ref=f"order:{order_id}",
                now=now,
            )
        except book.PaperError as e:
            conn.execute(
                "UPDATE paper_order SET status='FAILED', failure=%s WHERE order_id=%s",
                (str(e), order_id),
            )
            failed += 1
            continue
        detail = {
            "schedule": ch.schedule_id,
            "version": ch.schedule_version,
            "status": ch.schedule_status,
            "slippage_bps": str(slippage_bps),
            "lines": [[ln.type, str(ln.amount)] for ln in ch.lines],
        }
        conn.execute(
            "UPDATE paper_order SET status='FILLED', fill_day=%s, fill_price=%s, fill_commission=%s, fill_charges=%s, filled_at=%s WHERE order_id=%s",
            (day, price, ch.amount("COMMISSION"), Jsonb(detail), now, order_id),
        )
        filled += 1
    return FillReport(filled, failed, waiting)
