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
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg
from psycopg.types.json import Jsonb

from algo.backtest.costs.policy import CostPolicy
from algo.backtest.costs.slippage import fill_price
from algo.paper import book
from algo.paper import oms as paper_oms
from algo.paper import risk as paper_risk

IST = ZoneInfo("Asia/Kolkata")
COLUMNS = (
    "o.order_id, o.user_id, o.decision_day, o.instrument_id, i.symbol, o.side, o.qty, o.ref_price, o.reason, o.status,"
    " o.created_at, o.not_before, o.expires_at, o.decided_at, o.fill_day, o.fill_price, o.fill_commission, o.filled_at, o.failure,"
    " o.order_type, o.limit_price"
)
KEYS = [c.split(".")[1] for c in COLUMNS.replace(" ", "").split(",")]


LIMIT_BAND = Decimal(
    "0.20"
)  # a limit further than this from the reference close is a typo, not a price


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


def tick_size(conn: psycopg.Connection, instrument_id: int) -> Decimal | None:
    """The exchange's price step for a stock: Kite's own value when we have it, else the master's (a default for stocks Kite does not list)."""
    row = conn.execute(
        "SELECT coalesce((SELECT tick_size FROM kite_instrument WHERE instrument_id=%s AND tick_size IS NOT NULL"
        " ORDER BY active DESC, refreshed_at DESC LIMIT 1),"
        " (SELECT tick_size FROM instrument_terms WHERE instrument_id=%s AND valid_to IS NULL))",
        (instrument_id, instrument_id),
    ).fetchone()
    return None if row is None else row[0]


def snap_to_tick(price: Decimal, tick: Decimal) -> Decimal:
    """The nearest allowed price (a half step rounds up)."""
    return (price / tick).to_integral_value(ROUND_HALF_UP) * tick


def _how_sent(
    conn: psycopg.Connection,
    order_id: UUID,
    order_type: str,
    limit_price: Decimal | None,
) -> None:
    """Record how the owner chose to send the order (before the risk check, which looks at the price)."""
    if order_type == "MARKET":
        if limit_price is not None:
            raise OrderError("a market order has no limit price")
    elif order_type == "LIMIT":
        if limit_price is None or not limit_price.is_finite() or limit_price <= 0:
            raise OrderError("a limit order needs a limit price above zero")
        ref = conn.execute(
            "SELECT ref_price, instrument_id FROM paper_order WHERE order_id=%s", (order_id,)
        ).fetchone()
        assert ref is not None
        tick = tick_size(conn, ref[1])
        if tick is None:
            raise OrderError("the price step of this stock is not known, so a limit cannot be set")
        limit_price = snap_to_tick(limit_price, tick)  # only multiples of the tick are valid prices
        if limit_price <= 0:
            raise OrderError(f"the limit rounds to zero at this stock's price step {tick}")
        if abs(limit_price - ref[0]) > ref[0] * LIMIT_BAND:
            raise OrderError(
                f"the limit {limit_price} is more than {LIMIT_BAND:.0%} from the reference price {ref[0]}"
            )
    else:
        raise OrderError("the order type is MARKET or LIMIT")
    conn.execute(
        "UPDATE paper_order SET order_type=%s, limit_price=%s WHERE order_id=%s",
        (order_type, limit_price, order_id),
    )


def approve(
    conn: psycopg.Connection,
    order_id: UUID,
    *,
    user_id: UUID,
    now: datetime,
    order_type: str = "MARKET",
    limit_price: Decimal | None = None,
) -> None:
    _answerable(conn, order_id, user_id, now)
    acct = book.get_account(conn, user_id)
    if acct is None or not acct["enabled"] or acct["attention"]:
        raise OrderError("the account is paused, so orders cannot be approved")
    _how_sent(conn, order_id, order_type, limit_price)
    decision = paper_risk.check_approval(
        conn, user_id, order_id, now
    )  # approval is when an order is "sent"
    if not decision.approved:
        raise OrderError(
            "risk: "
            + ", ".join(decision.codes)
            + " - "
            + "; ".join(r.detail for r in decision.rejections)
        )
    sent = paper_oms.submit_approved(
        conn, user_id, order_id, now
    )  # through the OMS to the paper broker
    if sent.is_terminal:  # the OMS refused it (the risk checks again, with the book as it is now)
        raise OrderError(sent.reason)


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
    paper_oms.sync(conn, now)
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
    switch = paper_risk.load_switch(conn)
    due = conn.execute(
        "SELECT order_id, user_id, instrument_id, side, qty, not_before, expires_at, decided_at, limit_price, reason FROM paper_order WHERE status='APPROVED' AND expires_at > %s ORDER BY created_at, order_id",
        (now,),
    ).fetchall()
    for order_id, user_id, iid, side, qty, not_before, expires_at, decided_at, limit, why in due:
        acct = book.get_account(conn, user_id)
        if (
            acct is not None
            and switch.mode(acct["strategy_id"]).cancels_open
            and not why.startswith(
                paper_oms.FLATTEN_REASON
            )  # a flatten's own closing order is what the switch asked for
        ):
            conn.execute(
                "UPDATE paper_order SET status='FAILED', failure=%s WHERE order_id=%s",
                (
                    f"cancelled by the kill switch: {paper_risk.why(switch, acct['strategy_id'])}",
                    order_id,
                ),
            )
            failed += 1
            continue
        reach = (  # a limit order waits for a minute that trades at its price or better
            "" if limit is None else (" AND low <= %s" if side == "BUY" else " AND high >= %s")
        )
        bar = conn.execute(
            "SELECT ts, open FROM live_bar_1m WHERE instrument_id=%s AND ts >= %s AND ts < %s"
            + reach
            + " ORDER BY ts LIMIT 1",
            (
                iid,
                max(not_before, _next_minute(decided_at)),
                expires_at,
                *(() if limit is None else (limit,)),
            ),
        ).fetchone()
        if acct is None or not acct["enabled"] or acct["attention"] or bar is None:
            waiting += 1
            continue
        day = bar[0].astimezone(IST).date()
        if limit is None:
            price = fill_price(bar[1], side, slippage_bps)
        else:  # the limit or better: the open when it already is, else the limit; no slippage on top
            price = min(bar[1], limit) if side == "BUY" else max(bar[1], limit)
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
    paper_oms.sync(conn, now)  # hand the fills, refusals and cancellations to the OMS
    return FillReport(filled, failed, waiting)
