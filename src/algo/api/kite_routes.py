# ruff: noqa: E501
"""The signed-in user's own Kite connection. Every route acts on the caller's own record: there is no user id in any path, so
no one can reach another person's credentials. Responses never contain the API key, secret or token."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from algo.api.security import CurrentUser, PortalSettings, WConn
from algo.execution.broker import BrokerError
from algo.execution.kite_account import KiteAccount, KiteSessionExpired
from algo.portal import kite_vault

router = APIRouter(prefix="/api/kite", tags=["kite"])


class CredentialsBody(BaseModel):
    api_key: str = Field(max_length=100)
    api_secret: str = Field(max_length=100)


class CompleteBody(BaseModel):
    request_token: str = Field(max_length=200)
    state: str = Field(max_length=200)


class SystemBody(BaseModel):
    enabled: bool


def _settings(request: Request) -> PortalSettings:
    st: PortalSettings = request.app.state.portal
    return st


def _fail(e: kite_vault.KiteVaultError) -> HTTPException:
    return HTTPException(e.status, str(e))


@router.get("/connection")
def connection(request: Request, who: CurrentUser, conn: WConn) -> dict[str, Any]:
    st = _settings(request)
    return kite_vault.get_connection(
        conn, user_id=who.session.user_id, now=st.clock.now(), public_url=st.public_url
    )


@router.post("/credentials")
def save_credentials(
    body: CredentialsBody, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, bool]:
    st = _settings(request)
    try:
        kite_vault.save_credentials(
            conn,
            st.ring,
            user_id=who.session.user_id,
            api_key=body.api_key,
            api_secret=body.api_secret,
            now=st.clock.now(),
        )
    except kite_vault.KiteVaultError as e:
        raise _fail(e) from e
    return {"ok": True}


@router.post("/credentials/remove")
def remove_credentials(request: Request, who: CurrentUser, conn: WConn) -> dict[str, bool]:
    return {
        "ok": kite_vault.remove_credentials(
            conn, user_id=who.session.user_id, now=_settings(request).clock.now()
        )
    }


@router.post("/connect/start")
def connect_start(request: Request, who: CurrentUser, conn: WConn) -> dict[str, str]:
    st = _settings(request)
    try:
        return {
            "login_url": kite_vault.begin_connect(
                conn, st.ring, user_id=who.session.user_id, now=st.clock.now()
            )
        }
    except kite_vault.KiteVaultError as e:
        raise _fail(e) from e


@router.post("/connect/complete")
def connect_complete(
    body: CompleteBody, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, str]:
    st = _settings(request)
    try:
        kite_user = kite_vault.complete_connect(
            conn,
            st.ring,
            st.kite_http,
            user_id=who.session.user_id,
            request_token=body.request_token,
            state=body.state,
            now=st.clock.now(),
        )
    except kite_vault.KiteVaultError as e:
        conn.commit()  # a refused attempt keeps its state spent (and its audit entry)
        raise _fail(e) from e
    return {"kite_user": kite_user}


@router.post("/disconnect")
def disconnect(request: Request, who: CurrentUser, conn: WConn) -> dict[str, bool]:
    kite_vault.disconnect(conn, user_id=who.session.user_id, now=_settings(request).clock.now())
    return {"ok": True}


@router.get("/system")
def system_feed(request: Request, conn: WConn) -> dict[str, Any]:
    return {"feed": kite_vault.system_feed(conn, now=_settings(request).clock.now())}


@router.post("/system")
def set_system_feed(
    body: SystemBody, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, bool]:
    """The administrator's own connection becomes (or stops being) the data feed the loaders use."""
    try:
        kite_vault.set_system_feed(
            conn,
            actor=who.session.user_id,
            user_id=who.session.user_id,
            enabled=body.enabled,
            now=_settings(request).clock.now(),
        )
    except kite_vault.KiteVaultError as e:
        raise _fail(e) from e
    return {"ok": True}


def _num(d: Decimal) -> str:
    return format(d.normalize() if d == d.to_integral_value() else d, "f")


def platform_quantities() -> dict[str, int]:
    """Shares the platform itself bought at Kite, by trading symbol. No live order exists yet (live trading is not switched on), so none: every
    share in the account is outside the platform. Live orders will fill this from the OMS's own fills, never from the broker's totals."""
    return {}


def instrument_ids(conn: Any, symbols: list[str]) -> dict[str, int]:
    """Our instrument id for each Kite trading symbol (so a row can open its detail page). The NSE alias first, then Kite's own mapping over it
    (its rows are read oldest first, inactive before active, so the active newest one is the last and wins)."""
    out: dict[str, int] = {}
    if not symbols:
        return out
    for sql in (
        "SELECT source_symbol, instrument_id FROM instrument_alias WHERE source='nse' AND valid_to IS NULL AND source_symbol = ANY(%s)",
        "SELECT tradingsymbol, instrument_id FROM kite_instrument WHERE tradingsymbol = ANY(%s) AND instrument_id IS NOT NULL ORDER BY active, refreshed_at",
    ):
        for symbol, iid in conn.execute(sql, (symbols,)).fetchall():
            out[symbol] = int(iid)
    return out


@router.get("/account")
def account(request: Request, who: CurrentUser, conn: WConn) -> dict[str, Any]:
    """The signed-in person's own Kite holdings, today's positions and cash, read from Kite now (read only). A missing or ended session,
    or Kite not answering, is a state in the answer (nothing guessed), not an error."""
    st = _settings(request)
    now = st.clock.now()
    link = kite_vault.get_connection(
        conn, user_id=who.session.user_id, now=now, public_url=st.public_url
    )
    empty: dict[str, Any] = {
        "state": "ok",
        "message": None,
        "read_at": None,
        "kite_user_id": link["kite_user_id"],
        "cash": None,
        "holdings": [],
        "positions": [],
        "totals": {"holdings_value": "0", "holdings_pnl": "0"},
    }
    if link["state"] in ("not_configured", "saved"):
        return {**empty, "state": "not_connected"}
    creds = kite_vault.user_credentials(conn, st.ring, user_id=who.session.user_id, now=now)
    if creds is None:
        return {**empty, "state": "expired"}
    try:
        acct = KiteAccount(creds[0], creds[1], st.kite_http).read()
    except KiteSessionExpired:
        return {**empty, "state": "expired"}
    except BrokerError as e:
        return {**empty, "state": "unavailable", "message": str(e)}
    own = platform_quantities()
    ids = instrument_ids(
        conn, [*{h.symbol for h in acct.holdings}, *{p.symbol for p in acct.positions}]
    )
    holdings = [
        {
            "symbol": h.symbol,
            "instrument_id": ids.get(h.symbol),
            "quantity": str(h.total),
            "unsettled": str(h.unsettled),
            "average_price": _num(h.average_price),
            "last_price": _num(h.last_price),
            "value": _num(h.last_price * h.total),
            "pnl": _num(h.pnl),
            "platform_qty": str(min(own.get(h.symbol, 0), h.total)),
            "outside_qty": str(h.total - min(own.get(h.symbol, 0), h.total)),
        }
        for h in acct.holdings
    ]
    return {
        **empty,
        "read_at": now.isoformat(),
        "cash": _num(acct.cash),
        "holdings": holdings,
        "positions": [
            {
                "symbol": p.symbol,
                "instrument_id": ids.get(p.symbol),
                "product": p.product,
                "quantity": str(p.quantity),
                "average_price": _num(p.average_price),
                "last_price": _num(p.last_price),
                "pnl": _num(p.pnl),
            }
            for p in acct.positions
        ],
        "totals": {
            "holdings_value": _num(
                sum((h.last_price * h.total for h in acct.holdings), Decimal(0))
            ),
            "holdings_pnl": _num(sum((h.pnl for h in acct.holdings), Decimal(0))),
        },
    }
