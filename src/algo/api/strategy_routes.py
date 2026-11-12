# ruff: noqa: E501
"""Strategies: the signed-in user's saved, named strategy settings (index, number of stocks, time frame, rules).

Every route acts on the caller's own strategies (no user id in any path); an id that is not theirs looks like it does not
exist. The paper account picks one (`use`) and follows later edits of it. UNVALIDATED research: nothing here can place a
real order."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from algo.api import queries
from algo.api.paper_routes import _options, _params, _st
from algo.api.security import CurrentUser, WConn
from algo.paper import configs
from algo.portal import audit
from algo.strategies.signals import replay
from algo.strategies.trend_pullback import LOOKBACK_DAYS, TrendPullbackParams

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


class StrategyBody(BaseModel):
    name: str = Field(max_length=60)
    universe: str = Field(max_length=20)
    max_instruments: int | None = Field(default=None, ge=5, le=500)
    timeframe: str = Field(max_length=5)
    params: dict[str, int] = Field(default_factory=dict)


def _shown(c: dict[str, Any]) -> dict[str, Any]:
    return {**c, "config_id": str(c["config_id"]), "created_at": c["created_at"].isoformat()}


def _fail(e: configs.ConfigError) -> HTTPException:
    return HTTPException(404 if "no such" in str(e) else 400, str(e))


@router.get("")
def list_strategies(who: CurrentUser, conn: WConn) -> dict[str, Any]:
    return {
        "label": "UNVALIDATED",
        "options": _options(),
        "strategies": [_shown(c) for c in configs.list_for(conn, who.session.user_id)],
    }


def _change(
    request: Request,
    who: CurrentUser,
    conn: WConn,
    action: str,
    config_id: UUID,
    detail: dict[str, Any],
) -> None:
    audit.record(
        conn,
        now=_st(request).clock.now(),
        action=f"strategy.{action}",
        actor_user_id=who.session.user_id,
        target_type="strategy_config",
        target_id=str(config_id),
        detail=detail,
    )


@router.post("")
def create(body: StrategyBody, request: Request, who: CurrentUser, conn: WConn) -> dict[str, str]:
    params = _params(body.params)
    try:
        config_id = configs.create(
            conn, who.session.user_id, name=body.name, universe=body.universe,
            max_instruments=body.max_instruments, timeframe=body.timeframe, params=params,
            now=_st(request).clock.now(),
        )  # fmt: skip
    except configs.ConfigError as e:
        raise _fail(e) from e
    _change(
        request,
        who,
        conn,
        "created",
        config_id,
        {"name": body.name.strip(), "universe": body.universe},
    )
    return {"config_id": str(config_id)}


@router.post("/{config_id}")
def change(
    config_id: UUID, body: StrategyBody, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, bool]:
    params = _params(body.params)
    try:
        configs.update(
            conn, who.session.user_id, config_id, name=body.name, universe=body.universe,
            max_instruments=body.max_instruments, timeframe=body.timeframe, params=params,
        )  # fmt: skip
    except configs.ConfigError as e:
        raise _fail(e) from e
    _change(
        request,
        who,
        conn,
        "changed",
        config_id,
        {"name": body.name.strip(), "universe": body.universe, "params": params},
    )
    return {"ok": True}


@router.post("/{config_id}/use")
def use(config_id: UUID, request: Request, who: CurrentUser, conn: WConn) -> dict[str, bool]:
    try:
        configs.use(conn, who.session.user_id, config_id)
    except configs.ConfigError as e:
        raise _fail(e) from e
    _change(request, who, conn, "used", config_id, {})
    return {"ok": True}


@router.post("/{config_id}/delete")
def delete(config_id: UUID, request: Request, who: CurrentUser, conn: WConn) -> dict[str, bool]:
    try:
        configs.delete(conn, who.session.user_id, config_id)
    except configs.ConfigError as e:
        raise _fail(e) from e
    _change(request, who, conn, "deleted", config_id, {})
    return {"ok": True}


NOTES = [
    "Decisions only: this is not a backtest and shows no profit or loss.",
    "It reads one stock alone. It ignores the limit on how many stocks are held at once, the choice among stocks that are oversold on the same day, and index membership, so a BUY here is the strategy's signal for this stock, not a promise the whole strategy would have bought it.",
    "A decision is made after the day's close and filled at the next session's open.",
]
MAX_SIGNAL_DAYS = 366 * 10


@router.get("/{config_id}/signals")
def signals(
    config_id: UUID,
    instrument_id: int,
    start: date,
    end: date,
    who: CurrentUser,
    conn: WConn,
    holding: bool = False,
) -> dict[str, Any]:
    """One stock's buy/sell decisions under this strategy from `start` to `end`; `holding` starts the replay already holding it."""
    mine = configs.get(conn, who.session.user_id, config_id)
    if mine is None:
        raise HTTPException(404, "no such strategy")
    if end < start:
        raise HTTPException(422, "end before start")
    if (end - start).days > MAX_SIGNAL_DAYS:
        raise HTTPException(422, "range longer than 10 years")
    if queries.instrument(conn, instrument_id) is None:
        raise HTTPException(404, f"no instrument {instrument_id}")
    params = TrendPullbackParams(**mine["params"])
    history = queries.reader_for(conn, instrument_id)[0].issuer_history(
        instrument_id, start - timedelta(days=LOOKBACK_DAYS), end, adjust="split"
    )
    rows = replay(history.bars, params, start, end, holding=holding)
    days = [
        {
            "day": r.day.isoformat(), "close": _num(r.close), "sma": _num(r.sma), "rsi": _num(r.rsi), "ready": r.ready,
            "action": r.action, "reason": r.reason, "holding_after": r.holding_after,
            "fill_day": r.fill_day.isoformat() if r.fill_day else None, "fill_price": _num(r.fill_price),
        }
        for r in rows
    ]  # fmt: skip
    return {
        "label": "UNVALIDATED",
        "strategy": mine["name"],
        "params": mine["params"],
        "notes": NOTES,
        "summary": {
            "buys": sum(r.action == "BUY" for r in rows),
            "sells": sum(r.action == "SELL" for r in rows),
        },
        "days": days,
    }


def _num(d: Decimal | None) -> str | None:
    return None if d is None else format(d.normalize(), "f")
