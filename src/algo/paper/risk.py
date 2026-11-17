# ruff: noqa: E501
"""Risk limits and the kill switch for paper trading. Approval is the moment an order is 'sent', so that is where the limits are
enforced (a breach refuses the approval and the order stays PENDING); a CANCEL or FLATTEN switch also fails approved orders that
have not filled. Values are at cost (no live marks here), sectors are not known, and today's loss is not tracked, so the sector,
daily-loss and margin-by-mark limits are not meaningful on paper yet. The rate limit needs a long-lived engine and is not applied."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg
from psycopg.types.json import Jsonb

from algo.paper import book
from algo.risk import store
from algo.risk.engine import RiskEngine
from algo.risk.killswitch import KillSwitch
from algo.risk.limits import Limits
from algo.risk.model import Book, Day, Decision, Market, OrderRequest, Rejection, Side

IST = ZoneInfo("Asia/Kolkata")
__all__ = ["Limits", "check_approval", "get_limits", "inputs", "load_switch", "set_limits", "why"]


def get_limits(conn: psycopg.Connection, user_id: UUID) -> Limits:
    row = conn.execute("SELECT risk FROM paper_account WHERE user_id=%s", (user_id,)).fetchone()
    return Limits() if row is None or row[0] is None else Limits.from_mapping(row[0])


def set_limits(conn: psycopg.Connection, user_id: UUID, raw: Mapping[str, Any] | None) -> None:
    """Store the account's limits (None removes them). The mapping is validated first: a typo is refused, never ignored."""
    if raw is not None:
        Limits.from_mapping(raw)
    conn.execute(
        "UPDATE paper_account SET risk=%s WHERE user_id=%s",
        (None if raw is None else Jsonb(dict(raw)), user_id),
    )


def why(switch: KillSwitch, strategy_id: str) -> str:
    """The reason of the latest event that cancels open orders for this strategy."""
    return next(
        (
            e.reason
            for e in reversed(switch.events)
            if e.scope in (None, strategy_id) and e.mode.cancels_open
        ),
        "",
    )


def load_switch(conn: psycopg.Connection) -> KillSwitch:
    return store.load(conn)


def inputs(
    conn: psycopg.Connection, user_id: UUID, order_id: UUID, now: datetime
) -> tuple[OrderRequest, Market, Book, Day]:
    """What the risk engine looks at for this order: the request, the market, the account's book and today's activity."""
    acct = book.get_account(conn, user_id)
    assert acct is not None
    order = conn.execute(
        "SELECT instrument_id, side, qty, ref_price, limit_price FROM paper_order WHERE order_id=%s",
        (order_id,),
    ).fetchone()
    assert order is not None
    iid, side, qty, ref, limit = order
    if qty != qty.to_integral_value():
        raise ValueError(f"quantity {qty} is not a whole number")
    ledger = book.load(conn, user_id)
    held = {i: q for i, q in ledger.quantities().items() if q != 0}
    values = {i: ledger.cost_basis(i) for i in held}
    today = now.astimezone(IST).date()
    day_row = conn.execute(
        "SELECT count(*), coalesce(sum(qty * ref_price), 0) FROM paper_order WHERE user_id=%s AND status IN ('APPROVED', 'FILLED') AND order_id <> %s"
        " AND (decided_at AT TIME ZONE 'Asia/Kolkata')::date=%s",
        (user_id, order_id, today),
    ).fetchone()
    assert day_row is not None
    count, turnover = day_row
    open_row = conn.execute(
        "SELECT count(*) FROM paper_order WHERE user_id=%s AND status='APPROVED' AND order_id <> %s",
        (user_id, order_id),
    ).fetchone()
    assert open_row is not None
    request = OrderRequest(
        acct["strategy_id"], iid, Side(side), int(qty), limit, reduce_only=side == "SELL"
    )
    state = Book(
        position_qty=int(held.get(iid, 0)),
        instrument_value=values.get(iid, Decimal(0)),
        gross_value=sum(values.values(), Decimal(0)),
        net_value=sum(values.values(), Decimal(0)),
        margin_available=ledger.cash,
        open_orders=open_row[0],
    )
    return request, Market(ltp=Decimal(ref)), state, Day(orders=count, turnover=Decimal(turnover))


def check_approval(
    conn: psycopg.Connection, user_id: UUID, order_id: UUID, now: datetime
) -> Decision:
    try:
        request, market, state, day = inputs(conn, user_id, order_id, now)
    except ValueError as e:
        return Decision((Rejection("BAD_QTY", str(e)),))
    return RiskEngine(get_limits(conn, user_id), store.load(conn)).approve(
        request, market, state, day, now
    )
