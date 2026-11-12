# ruff: noqa: E501
"""Trading-cost schedules: everyone signed in can read them and try a trade through the calculator; administrators (system:settings)
verify a schedule, enter a price change with its effective date, extend current rates over earlier history as a flagged
assumption, or remove an unverified one. Every change is audited. Money leaves as decimal strings (never floats)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from algo.api.security import CurrentUser, PortalSettings, WConn
from algo.backtest.costs import schedule_store
from algo.backtest.costs.calculator import compute_charges
from algo.backtest.costs.schedule import NoScheduleForDate, ScheduleError
from algo.portal import audit

router = APIRouter(prefix="/api/costs", tags=["costs"])
ANY_STATUS = ("verified", "extracted_unverified", "assumed_backfill")


class BackfillBody(BaseModel):
    valid_from: date


class Change(BaseModel):
    type: str = Field(max_length=40)
    side: str = Field(max_length=4)
    rate_pct: Decimal | None = None
    amount: Decimal | None = None
    minimum: Decimal | None = None
    maximum: Decimal | None = None


class ProviderBody(BaseModel):
    name: str = Field(max_length=60)
    template_broker: str = Field(max_length=60)
    valid_from: date
    note: str = Field(default="", max_length=500)


class NewVersionBody(BaseModel):
    valid_from: date
    valid_until: date | None = None
    note: str = Field(default="", max_length=500)
    changes: list[Change] = Field(max_length=20)


def _s(d: Decimal | None) -> str | None:
    return None if d is None else format(d.normalize(), "f")


def _st(request: Request) -> PortalSettings:
    st: PortalSettings = request.app.state.portal
    return st


def _fail(e: ScheduleError) -> HTTPException:
    return HTTPException(404 if str(e).startswith("no such schedule") else 400, str(e))


def _row(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "schedule_id": r["schedule_id"], "version": r["version"], "name": r["name"], "broker": r["broker"], "product": r["product"],
        "valid_from": r["valid_from"].isoformat(), "valid_until": None if r["valid_until"] is None else r["valid_until"].isoformat(),
        "status": r["status"], "verified_by": r["verified_by"], "verified_at": None if r["verified_at"] is None else r["verified_at"].isoformat(),
        "notes": r["notes"], "contract_note_min_brokerage": _s(r["contract_note_min_brokerage"]),
        "components": [{**c, "rate_pct": _s(c["rate_pct"]), "amount": _s(c["amount"]), "minimum": _s(c["minimum"]), "maximum": _s(c["maximum"])} for c in r["components"]],
        "sources": r["sources"],
    }  # fmt: skip


@router.get("/schedules")
def schedules(conn: WConn) -> dict[str, Any]:
    return {"schedules": [_row(r) for r in schedule_store.list_schedules(conn)]}


@router.get("/preview")
def preview(
    conn: WConn, broker: str, product: str, side: str, qty: Decimal, price: Decimal, day: date
) -> dict[str, Any]:
    """What one executed order would cost on `day`, itemised, using whichever schedule covers it (assumptions included, and named)."""
    try:
        sch = schedule_store.load_book(conn, broker, ANY_STATUS).for_date(day, product)
        ch = compute_charges(sch, side, qty, price)
    except NoScheduleForDate as e:
        raise HTTPException(404, str(e)) from e
    except (ScheduleError, ValueError) as e:
        raise HTTPException(400, str(e)) from e
    return {
        "schedule": {"id": sch.id, "version": sch.version, "status": sch.status, "valid_from": sch.valid_from.isoformat(), "valid_until": None if sch.valid_until is None else sch.valid_until.isoformat()},
        "value": _s(qty * price), "lines": [{"type": ln.type, "amount": _s(ln.amount), "formula": ln.formula} for ln in ch.lines], "total": _s(ch.total),
    }  # fmt: skip


def _log(
    conn: Any,
    request: Request,
    who: CurrentUser,
    action: str,
    schedule_id: str,
    version: str,
    **detail: Any,
) -> None:
    audit.record(
        conn,
        now=_st(request).clock.now(),
        action=f"costs.{action}",
        actor_user_id=who.session.user_id,
        target_type="cost_schedule",
        target_id=f"{schedule_id}/{version}",
        detail=detail,
    )


@router.post("/providers")
def add_provider(
    body: ProviderBody, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, bool]:
    try:
        made = schedule_store.add_provider(
            conn,
            body.name,
            template_broker=body.template_broker,
            valid_from=body.valid_from,
            note=body.note,
            by=who.session.display_name,
            actor=who.session.user_id,
            now=_st(request).clock.now(),
        )
    except ScheduleError as e:
        raise _fail(e) from e
    audit.record(
        conn,
        now=_st(request).clock.now(),
        action="costs.provider_added",
        actor_user_id=who.session.user_id,
        target_type="cost_provider",
        target_id=made[0].broker,
        detail={
            "template": body.template_broker,
            "valid_from": body.valid_from.isoformat(),
            "note": body.note,
        },
    )
    return {"ok": True}


@router.post("/schedules/{schedule_id}/{version}/verify")
def verify(
    schedule_id: str, version: str, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, bool]:
    try:
        schedule_store.verify(
            conn, schedule_id, version, by=who.session.display_name, now=_st(request).clock.now()
        )
    except ScheduleError as e:
        raise _fail(e) from e
    _log(conn, request, who, "verified", schedule_id, version)
    return {"ok": True}


@router.post("/schedules/{schedule_id}/{version}/backfill")
def backfill(
    schedule_id: str,
    version: str,
    body: BackfillBody,
    request: Request,
    who: CurrentUser,
    conn: WConn,
) -> dict[str, bool]:
    try:
        schedule_store.backfill(
            conn,
            schedule_id,
            version,
            valid_from=body.valid_from,
            actor=who.session.user_id,
            now=_st(request).clock.now(),
        )
    except ScheduleError as e:
        raise _fail(e) from e
    _log(
        conn,
        request,
        who,
        "backfilled",
        schedule_id,
        version,
        valid_from=body.valid_from.isoformat(),
    )
    return {"ok": True}


@router.post("/schedules/{schedule_id}/{version}/new-version")
def new_version(
    schedule_id: str,
    version: str,
    body: NewVersionBody,
    request: Request,
    who: CurrentUser,
    conn: WConn,
) -> dict[str, bool]:
    changes = [c.model_dump(include=c.model_fields_set) for c in body.changes]
    try:
        schedule_store.add_version(
            conn,
            schedule_id,
            version,
            valid_from=body.valid_from,
            valid_until=body.valid_until,
            changes=changes,
            note=body.note,
            by=who.session.display_name,
            actor=who.session.user_id,
            now=_st(request).clock.now(),
        )
    except ScheduleError as e:
        raise _fail(e) from e
    _log(
        conn,
        request,
        who,
        "version_added",
        schedule_id,
        version,
        valid_from=body.valid_from.isoformat(),
        changes=[
            {k: (str(v) if isinstance(v, Decimal) else v) for k, v in c.items()} for c in changes
        ],
        note=body.note,
    )
    return {"ok": True}


@router.post("/schedules/{schedule_id}/{version}/remove")
def remove(
    schedule_id: str, version: str, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, bool]:
    try:
        schedule_store.remove(conn, schedule_id, version)
    except ScheduleError as e:
        raise _fail(e) from e
    _log(conn, request, who, "removed", schedule_id, version)
    return {"ok": True}
