# ruff: noqa: E501
"""Paper trading for the signed-in user: their account and settings, what it holds, the orders waiting for their answer.

Every route acts on the caller's own account (no user id in any path), so nobody can reach anyone else's; an order id that
is not theirs looks like it does not exist. Money and quantities leave as decimal STRINGS (never floats) and are only ever
formatted by the browser. UNVALIDATED research: nothing here can place a real order."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal, get_args
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError

from algo.api.security import CurrentUser, PortalSettings, WConn
from algo.data.corporate_actions import upcoming_within
from algo.live.market_calendar import IST
from algo.paper import book, orders
from algo.paper.universe import UNIVERSES
from algo.portal import audit
from algo.strategies.trend_pullback import TrendPullbackParams

router = APIRouter(prefix="/api/paper", tags=["paper"])
TIMEFRAMES = (("1D", "Daily", True), ("1h", "1 hour", False), ("15m", "15 minutes", False))
STATUSES = {"PENDING", "APPROVED", "REJECTED", "EXPIRED", "FILLED", "FAILED"}
WARN_DAYS = 10  # an announced action this close is worth a look before an order is approved
OPEN = ("PENDING", "APPROVED")  # an order still to be decided or filled


def _heads_up(request: Request, conn: Any, ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    """Announced actions coming within WARN_DAYS for these instruments, ready to send."""
    today = _st(request).clock.now().astimezone(IST).date()
    return {
        iid: [
            {**u, "ex_date": u["ex_date"].isoformat(), "num": _opt(u["num"]), "den": _opt(u["den"]), "amount": _opt(u["amount"])}
            for u in items
        ]
        for iid, items in upcoming_within(conn, ids, today, WARN_DAYS).items()
    }  # fmt: skip


class CreateBody(BaseModel):
    initial_cash: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    universe: str = Field(default="nifty200", max_length=20)
    max_instruments: int | None = Field(default=None, ge=5, le=500)
    timeframe: str = Field(default="1D", max_length=5)
    params: dict[str, int] = Field(default_factory=dict)


class SettingsBody(BaseModel):
    enabled: bool | None = None
    universe: str | None = Field(default=None, max_length=20)
    max_instruments: int | None = Field(
        default=None, ge=5, le=500
    )  # an explicit null clears the cap
    timeframe: str | None = Field(default=None, max_length=5)
    params: dict[str, int] | None = None


def _s(d: Decimal) -> str:
    return format(
        d.normalize(), "f"
    )  # no scientific notation (20000 / 100 is Decimal('2E+2')) and no trailing zeros


def _opt(d: Decimal | None) -> str | None:
    return None if d is None else _s(d)


def _st(request: Request) -> PortalSettings:
    st: PortalSettings = request.app.state.portal
    return st


def _params(overrides: dict[str, int]) -> dict[str, int]:
    try:
        return TrendPullbackParams(
            **{**TrendPullbackParams().model_dump(), **overrides}
        ).model_dump()
    except ValidationError as e:
        why = "; ".join(f"{'.'.join(map(str, x['loc']))} {x['msg']}" for x in e.errors())
        raise HTTPException(400, f"those strategy settings are not allowed: {why}") from e


def _options() -> dict[str, Any]:
    return {
        "universes": [{"key": k, "label": label} for k, (label, _) in UNIVERSES.items()],
        "timeframes": [{"key": k, "label": label, "available": ok} for k, label, ok in TIMEFRAMES],
        "params": {
            name: list(get_args(f.annotation))
            for name, f in TrendPullbackParams.model_fields.items()
        },
    }


def _own(conn: Any, who: CurrentUser) -> dict[str, Any]:
    acct = book.get_account(conn, who.session.user_id)
    if acct is None:
        raise HTTPException(404, "no paper account yet")
    return acct


@router.get("/account")
def account(who: CurrentUser, conn: WConn) -> dict[str, Any]:
    acct = book.get_account(conn, who.session.user_id)
    shown = None
    if acct is not None:
        shown = {
            "strategy_id": acct["strategy_id"], "enabled": acct["enabled"], "mode": acct["mode"], "initial_cash": _s(acct["initial_cash"]),
            "started_on": acct["started_on"].isoformat(), "attention": acct["attention"], "universe": acct["universe"],
            "max_instruments": acct["max_instruments"], "timeframe": acct["timeframe"], "params": acct["params"], "screen": acct["screen"],
        }  # fmt: skip
    return {"label": "UNVALIDATED", "options": _options(), "account": shown}


@router.post("/account")
def create_account(
    body: CreateBody, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, bool]:
    now = _st(request).clock.now()
    params = _params(body.params)
    try:
        book.create_account(
            conn,
            who.session.user_id,
            strategy_id="trend_pullback",
            params=params,
            initial_cash=body.initial_cash,
            started_on=now.astimezone(IST).date(),
            now=now,
            universe=body.universe,
            max_instruments=body.max_instruments,
            timeframe=body.timeframe,
        )
    except book.PaperError as e:
        raise HTTPException(400, str(e)) from e
    audit.record(
        conn,
        now=now,
        action="paper.account_created",
        actor_user_id=who.session.user_id,
        target_type="paper_account",
        target_id=str(who.session.user_id),
        detail={
            "universe": body.universe,
            "max_instruments": body.max_instruments,
            "timeframe": body.timeframe,
            "initial_cash": _s(body.initial_cash),
        },
    )
    return {"ok": True}


@router.post("/account/settings")
def change_settings(
    body: SettingsBody, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, bool]:
    acct = _own(conn, who)
    changes: dict[str, Any] = {}
    if body.universe is not None:
        changes["universe"] = body.universe
    if "max_instruments" in body.model_fields_set:
        changes["max_instruments"] = body.max_instruments
    if body.timeframe is not None:
        changes["timeframe"] = body.timeframe
    if body.params is not None:
        changes["params"] = _params({**acct["params"], **body.params})
    try:
        book.update_settings(conn, who.session.user_id, **changes)
        if body.enabled is not None:
            book.set_enabled(conn, who.session.user_id, body.enabled)
    except book.PaperError as e:
        raise HTTPException(400, str(e)) from e
    detail = {**changes, **({"enabled": body.enabled} if body.enabled is not None else {})}
    audit.record(
        conn,
        now=_st(request).clock.now(),
        action="paper.settings_changed",
        actor_user_id=who.session.user_id,
        target_type="paper_account",
        target_id=str(who.session.user_id),
        detail=detail,
    )
    return {"ok": True}


@router.get("/summary")
def summary(request: Request, who: CurrentUser, conn: WConn) -> dict[str, Any]:
    uid = who.session.user_id
    _own(conn, who)
    ledger = book.load(conn, uid)
    held = ledger.quantities()
    prices: dict[int, Decimal] = dict(
        conn.execute(
            "SELECT DISTINCT ON (instrument_id) instrument_id, close FROM bar_1d WHERE instrument_id = ANY(%s) AND ts <= %s ORDER BY instrument_id, ts DESC",
            (list(held), _st(request).clock.now()),
        ).fetchall()
    )
    symbols: dict[int, str] = dict(
        conn.execute(
            "SELECT instrument_id, symbol FROM instrument WHERE instrument_id = ANY(%s)",
            (list(held),),
        ).fetchall()
    )
    marks = {
        iid: prices.get(iid, ledger.cost_basis(iid) / q) for iid, q in held.items()
    }  # no price yet: valued at cost
    equity, pnl = ledger.equity(marks), ledger.pnl(marks)
    heads_up = _heads_up(request, conn, list(held))
    positions = [
        {"instrument_id": iid, "symbol": symbols[iid], "qty": _s(q), "avg_cost": _s(ledger.cost_basis(iid) / q), "last_price": _s(marks[iid]), "value": _s(q * marks[iid]), "upcoming": heads_up.get(iid, []), "unrealized": _s(q * marks[iid] - ledger.cost_basis(iid))}
        for iid, q in sorted(held.items(), key=lambda kv: symbols[kv[0]])
    ]  # fmt: skip
    curve = conn.execute(
        "SELECT day, equity FROM paper_equity WHERE user_id=%s ORDER BY day", (uid,)
    ).fetchall()
    pending = conn.execute(
        "SELECT count(*) FROM paper_order WHERE user_id=%s AND status='PENDING'", (uid,)
    ).fetchone()
    assert pending is not None
    return {
        "equity": _s(equity), "cash": _s(ledger.cash), "invested": _s(equity - ledger.cash),
        "pnl": {"realized": _s(pnl.realized), "unrealized": _s(pnl.unrealized), "fees": _s(pnl.fees), "net": _s(pnl.net)},
        "positions": positions, "equity_curve": [{"day": d.isoformat(), "equity": _s(e)} for d, e in curve], "pending_orders": int(pending[0]),
    }  # fmt: skip


def _order(o: dict[str, Any], heads_up: dict[int, list[dict[str, Any]]]) -> dict[str, Any]:
    return {
        "order_id": str(o["order_id"]), "symbol": o["symbol"], "side": o["side"], "qty": _s(o["qty"]), "ref_price": _s(o["ref_price"]),
        "reason": o["reason"], "status": o["status"], "decision_day": o["decision_day"].isoformat(), "created_at": o["created_at"].isoformat(),
        "expires_at": o["expires_at"].isoformat(), "fill_price": _opt(o["fill_price"]), "fill_commission": _opt(o["fill_commission"]),
        "fill_day": None if o["fill_day"] is None else o["fill_day"].isoformat(), "failure": o["failure"], "order_type": o["order_type"], "limit_price": _opt(o["limit_price"]),
        "upcoming": heads_up.get(o["instrument_id"], []) if o["status"] in OPEN else [],  # nothing left to warn about once decided
    }  # fmt: skip


@router.get("/orders")
def list_orders(
    request: Request,
    who: CurrentUser,
    conn: WConn,
    status: str | None = Query(default=None, max_length=100),
) -> dict[str, Any]:
    wanted = None if status is None else [s for s in status.split(",") if s in STATUSES]
    if wanted is not None and not wanted:
        return {"orders": []}
    rows = orders.list_orders(conn, who.session.user_id, statuses=wanted)
    heads_up = _heads_up(request, conn, [o["instrument_id"] for o in rows if o["status"] in OPEN])
    return {"orders": [_order(o, heads_up) for o in rows]}


class ApproveBody(BaseModel):
    order_type: Literal["MARKET", "LIMIT"] = "MARKET"
    limit_price: Decimal | None = None


def _answer(
    action: str,
    order_id: str,
    request: Request,
    who: CurrentUser,
    conn: WConn,
    how: ApproveBody | None = None,
) -> dict[str, bool]:
    try:
        oid = UUID(order_id)
    except ValueError as e:
        raise HTTPException(404, "no such order") from e
    now = _st(request).clock.now()
    try:
        if action == "approved":
            how = how or ApproveBody()
            orders.approve(
                conn,
                oid,
                user_id=who.session.user_id,
                now=now,
                order_type=how.order_type,
                limit_price=how.limit_price,
            )
        else:
            orders.reject(conn, oid, user_id=who.session.user_id, now=now)
    except orders.OrderError as e:
        raise HTTPException(404 if str(e) == "no such order" else 400, str(e)) from e
    audit.record(
        conn,
        now=now,
        action=f"paper.order_{action}",
        actor_user_id=who.session.user_id,
        target_type="paper_order",
        target_id=order_id,
    )
    return {"ok": True}


@router.post("/orders/{order_id}/approve")
def approve_order(
    order_id: str,
    request: Request,
    who: CurrentUser,
    conn: WConn,
    body: ApproveBody | None = None,
) -> dict[str, bool]:
    return _answer("approved", order_id, request, who, conn, body)


@router.post("/orders/{order_id}/reject")
def reject_order(order_id: str, request: Request, who: CurrentUser, conn: WConn) -> dict[str, bool]:
    return _answer("rejected", order_id, request, who, conn)


@router.get("/runs")
def runs(who: CurrentUser, conn: WConn) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT r.decision_day, r.status, r.detail, r.strategy_version, r.created_at,"
        " (SELECT count(*) FROM paper_order o WHERE o.user_id = r.user_id AND o.decision_day = r.decision_day)"
        " FROM paper_run r WHERE r.user_id=%s ORDER BY r.decision_day DESC LIMIT 30",
        (who.session.user_id,),
    ).fetchall()
    return {
        "runs": [
            {
                "decision_day": day.isoformat(),
                "status": status,
                "reason": detail.get("reason"),
                "orders": int(n),
                "universe": (detail.get("universe") or {}).get("universe"),
                "strategy_version": version,
                "created_at": created.isoformat(),
            }
            for day, status, detail, version, created, n in rows
        ]
    }
