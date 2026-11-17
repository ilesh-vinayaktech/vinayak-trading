# ruff: noqa: E501
"""The risk page: the kill switch and the account's limits. A trader switches their own strategy; an operator switches everyone. Every
change is stored with who and why (kill_switch_event) and audited. UNVALIDATED research: nothing here can place a real order."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from algo.api.security import CurrentUser, PortalSettings, WConn
from algo.paper import book
from algo.paper import risk as paper_risk
from algo.portal import audit
from algo.risk import store
from algo.risk.killswitch import KillSwitch, KillSwitchError
from algo.risk.limits import LimitsError

router = APIRouter(prefix="/api/risk", tags=["risk"])
LIMIT_KEYS = [
    {"key": "allowed", "kind": "list", "help": "Only these instrument ids may be traded"},
    {"key": "restricted", "kind": "list", "help": "Instrument ids that may never be traded"},
    {"key": "max_order_qty", "kind": "integer", "help": "Largest order, in shares"},
    {"key": "max_order_value", "kind": "number", "help": "Largest order, in rupees"},
    {
        "key": "max_adv_fraction",
        "kind": "number",
        "help": "Order size as a fraction of average daily volume",
    },
    {
        "key": "fat_finger_band",
        "kind": "number",
        "help": "A limit price may differ from the last price by at most this fraction",
    },
    {
        "key": "max_instrument_value",
        "kind": "number",
        "help": "Largest position in one stock after the order, at cost",
    },
    {
        "key": "max_gross_value",
        "kind": "number",
        "help": "Largest total of all positions after the order, at cost",
    },
    {
        "key": "max_net_value",
        "kind": "number",
        "help": "Largest net exposure after the order, at cost",
    },
    {"key": "check_margin", "kind": "bool", "help": "A buy must fit in the cash available"},
    {"key": "max_open_orders", "kind": "integer", "help": "Approved orders waiting to fill"},
    {
        "key": "trading_hours",
        "kind": "hours",
        "help": 'Orders only between these Indian times, e.g. ["09:15", "15:30"]',
    },
    {"key": "max_daily_orders", "kind": "integer", "help": "Orders approved today"},
    {"key": "max_daily_turnover", "kind": "number", "help": "Rupees approved today"},
    {"key": "max_daily_loss", "kind": "number", "help": "Not tracked on paper yet"},
    {"key": "max_consecutive_failures", "kind": "integer", "help": "Failed orders in a row"},
]


def _st(request: Request) -> PortalSettings:
    st: PortalSettings = request.app.state.portal
    return st


class SwitchBody(BaseModel):
    action: Literal["pause", "cancel", "resume", "flatten"]
    reason: str = Field(max_length=300)
    emergency_override: bool = False

    @field_validator("reason")
    @classmethod
    def _needs_a_reason(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("say why")
        return v.strip()


class LimitsBody(BaseModel):
    limits: dict[str, Any]


def _last(switch: KillSwitch, scope: str | None) -> dict[str, Any] | None:
    ev = next((e for e in reversed(switch.events) if e.scope == scope), None)
    return (
        None
        if ev is None
        else {"mode": ev.mode.value, "by": ev.by, "reason": ev.reason, "ts": ev.ts.isoformat()}
    )


def _view(switch: KillSwitch, strategy_id: str | None) -> dict[str, Any]:
    own = _last(switch, strategy_id) if strategy_id else None
    scoped = [e for e in switch.events if e.scope is None or e.scope == strategy_id]
    return {
        "effective": switch.mode(strategy_id or "").value,
        "global": _last(switch, None),
        "strategy": own,
        "_events": [
            {
                "ts": e.ts.isoformat(),
                "scope": e.scope,
                "mode": e.mode.value,
                "by": e.by,
                "reason": e.reason,
            }
            for e in reversed(scoped)
        ][:20],
    }


def _email(conn: Any, who: CurrentUser) -> str:
    row = conn.execute(
        "SELECT email FROM portal_user WHERE user_id=%s", (who.session.user_id,)
    ).fetchone()
    assert row is not None
    return str(row[0])


def _mode(conn: Any, who: CurrentUser, mode: str | None) -> str:
    """The account the caller means: the one named, else their paper account, else their live one."""
    if mode is not None:
        return mode.upper()
    paper = book.get_account(conn, book.account_key(who.session.user_id, "PAPER"))
    return "PAPER" if paper is not None else "LIVE"


def _strategy(conn: Any, who: CurrentUser, mode: str | None = None) -> str | None:
    key = book.account_key(who.session.user_id, _mode(conn, who, mode))
    acct = book.get_account(conn, key)
    return None if acct is None else str(acct["strategy_id"])


@router.get("")
def state(
    who: CurrentUser, conn: WConn, mode: Literal["paper", "live"] | None = None
) -> dict[str, Any]:
    strategy_id = _strategy(conn, who, mode)
    view = _view(store.load(conn), strategy_id)
    events = view.pop("_events")
    limits = None
    if strategy_id is not None:
        row = conn.execute(
            "SELECT risk FROM paper_account WHERE user_id=%s",
            (book.account_key(who.session.user_id, _mode(conn, who, mode)),),
        ).fetchone()
        limits = (row[0] if row else None) or {}
    return {
        "label": "UNVALIDATED",
        "account": None if strategy_id is None else {"strategy_id": strategy_id},
        "switch": view,
        "events": events,
        "limits": limits,
        "limit_keys": LIMIT_KEYS,
        "can_global": "ops:write" in who.permissions,
    }


def _change(
    request: Request, who: CurrentUser, conn: Any, scope: str | None, body: SwitchBody
) -> dict[str, str]:
    try:
        switch = store.change(
            conn,
            body.action,
            scope,
            by=_email(conn, who),
            reason=body.reason,
            now=_st(request).clock.now(),
            emergency_override=body.emergency_override,
        )
    except KillSwitchError as e:
        raise HTTPException(400, str(e)) from e
    audit.record(
        conn,
        now=_st(request).clock.now(),
        action="risk.switch_changed",
        actor_user_id=who.session.user_id,
        target_type="kill_switch",
        target_id=scope or "global",
        detail={"action": body.action, "reason": body.reason},
    )
    return {"effective": switch.mode(scope or "").value}


@router.post("/switch")
def switch_own(body: SwitchBody, request: Request, who: CurrentUser, conn: WConn) -> dict[str, str]:
    strategy_id = _strategy(conn, who)
    if strategy_id is None:
        raise HTTPException(404, "no paper account yet")
    return _change(request, who, conn, strategy_id, body)


@router.post("/switch/global")
def switch_global(
    body: SwitchBody, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, str]:
    return _change(request, who, conn, None, body)


@router.put("/limits")
def set_limits(
    body: LimitsBody,
    request: Request,
    who: CurrentUser,
    conn: WConn,
    mode: Literal["paper", "live"] | None = None,
) -> dict[str, Any]:
    if _strategy(conn, who, mode) is None:
        raise HTTPException(404, "no trading account yet")
    key = book.account_key(who.session.user_id, _mode(conn, who, mode))
    try:
        paper_risk.set_limits(conn, key, body.limits or None)
    except (LimitsError, ValueError, TypeError, ArithmeticError) as e:
        raise HTTPException(422, str(e)) from e
    audit.record(
        conn,
        now=_st(request).clock.now(),
        action="risk.limits_changed",
        actor_user_id=who.session.user_id,
        target_type="paper_account",
        target_id=str(key),
        detail={"limits": body.limits},
    )
    return {"limits": body.limits}
