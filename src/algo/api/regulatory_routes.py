# ruff: noqa: E501
"""The regulatory page: the exchange and Kite rules live trading depends on, what is recorded, what blocks live, and the form that
records or re-verifies one. Anyone with research access may look; staff (ops:write) record. Nothing here reads or guesses a rule: the
person records what they read in the circular. Rows are append-only (regulatory_config), every change is audited."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from algo.api.security import CurrentUser, PortalSettings, WConn
from algo.execution import regulatory as reg
from algo.portal import audit

router = APIRouter(prefix="/api/regulatory", tags=["regulatory"])
TOPICS = {
    "ops_limit": (
        "Order-rate limit",
        "How many orders per second an algo may send before it needs exchange registration, as the circular states it.",
    ),
    "order_types": (
        "Order types and market protection",
        "Which order types an algo may use, and the market-protection setting the broker requires on market orders.",
    ),
    "tagging": (
        "Algo tagging",
        "How an algo order must be tagged or identified so the exchange can tell it from a manual order.",
    ),
    "static_ip": (
        "Static IP",
        "The rule on the fixed IP address algo orders must come from, and which address is registered.",
    ),
}
assert tuple(TOPICS) == reg.REQUIRED
FILL = "<fill in>"  # a template field nobody filled: refused, so a half-filled example cannot become the recorded rule
EXAMPLES: dict[
    str, dict[str, Any]
] = {  # a suggested layout only: the value is free-form and nothing reads its keys
    "ops_limit": {"orders_per_second_limit": FILL, "applies_above": FILL, "notes": FILL},
    "order_types": {"allowed_order_types": [FILL], "market_protection": FILL, "notes": FILL},
    "tagging": {"tag_required": FILL, "how_to_tag": FILL, "notes": FILL},
    "static_ip": {"required": FILL, "registered_ip": FILL, "notes": FILL},
}
assert tuple(EXAMPLES) == reg.REQUIRED


def _st(request: Request) -> PortalSettings:
    st: PortalSettings = request.app.state.portal
    return st


def _today(request: Request) -> date:
    return _st(request).clock.now().date()


class RecordBody(BaseModel):
    topic: str
    value: Any
    source: str = Field(max_length=500)
    effective_from: date

    @field_validator("topic")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in TOPICS:
            raise ValueError("unknown rule")
        return v

    @field_validator("value")
    @classmethod
    def _has_value(cls, v: Any) -> Any:
        if v is None or v == "" or v == {} or v == []:
            raise ValueError("record what the rule says")
        if FILL in json.dumps(v):
            raise ValueError(f"replace every {FILL} with what the rule says")
        return v

    @field_validator("source")
    @classmethod
    def _has_source(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("say where you read it (circular number or link)")
        return v.strip()


def _email(conn: Any, who: CurrentUser) -> str:
    row = conn.execute(
        "SELECT email FROM portal_user WHERE user_id=%s", (who.session.user_id,)
    ).fetchone()
    assert row is not None
    return str(row[0])


def _item(topic: str, i: reg.Item | None, today: date) -> dict[str, Any]:
    label, help_ = TOPICS[topic]
    out: dict[str, Any] = {
        "topic": topic,
        "label": label,
        "help": help_,
        "example": EXAMPLES[topic],
        "status": "missing",
        "value": None,
        "source": None,
        "effective_from": None,
        "last_verified": None,
        "verified_by": None,
        "expires_on": None,
        "days_since": None,
    }
    if i is None or i.effective_from > today:
        return out
    expires = i.last_verified + reg.MAX_AGE
    out.update(
        status="stale" if today - i.last_verified > reg.MAX_AGE else "ok",
        value=i.value,
        source=i.source,
        effective_from=i.effective_from.isoformat(),
        last_verified=i.last_verified.isoformat(),
        verified_by=i.verified_by,
        expires_on=expires.isoformat(),
        days_since=(today - i.last_verified).days,
    )
    return out


@router.get("")
def state(request: Request, who: CurrentUser, conn: WConn) -> dict[str, Any]:
    today = _today(request)
    found = reg.in_force(conn)
    have = {i.topic: i for i in found if (i.exchange, i.segment) == (reg.EXCHANGE, reg.SEGMENT)}
    problems = reg.problems(found, today)
    return {
        "today": today.isoformat(),
        "exchange": reg.EXCHANGE,
        "segment": reg.SEGMENT,
        "max_age_days": reg.MAX_AGE // timedelta(days=1),
        "blocks_live": bool(problems),
        "problems": problems,
        "items": [_item(t, have.get(t), today) for t in TOPICS],
        "can_edit": "ops:write" in who.permissions,
    }


def _save(
    request: Request, who: CurrentUser, conn: Any, item: reg.Item, action: str
) -> dict[str, str]:
    reg.record(conn, item)
    audit.record(
        conn,
        now=_st(request).clock.now(),
        action=action,
        actor_user_id=who.session.user_id,
        target_type="regulatory_config",
        target_id=item.topic,
        detail={
            "source": item.source,
            "effective_from": item.effective_from.isoformat(),
            "last_verified": item.last_verified.isoformat(),
        },
    )
    return {"topic": item.topic}


@router.post("")
def record(body: RecordBody, request: Request, who: CurrentUser, conn: WConn) -> dict[str, str]:
    today = _today(request)
    if body.effective_from > today:
        raise HTTPException(
            422,
            "a rule that is not in force yet cannot be recorded: the check would still call it missing",
        )
    item = reg.Item(
        reg.EXCHANGE,
        reg.SEGMENT,
        body.topic,
        body.value,
        body.effective_from,
        body.source,
        today,
        _email(conn, who),
    )
    return _save(request, who, conn, item, "regulatory.recorded")


@router.post("/{topic}/verify")
def verify(topic: str, request: Request, who: CurrentUser, conn: WConn) -> dict[str, str]:
    """A re-check: the rule is unchanged, so the same value is stored again with today's date and your name."""
    if topic not in TOPICS:
        raise HTTPException(422, "unknown rule")
    today = _today(request)
    now = next(
        (
            i
            for i in reg.in_force(conn)
            if (i.exchange, i.segment, i.topic) == (reg.EXCHANGE, reg.SEGMENT, topic)
            and i.effective_from <= today
        ),
        None,
    )
    if now is None:
        raise HTTPException(404, "nothing is recorded for this rule yet: record it first")
    item = reg.Item(
        now.exchange,
        now.segment,
        topic,
        now.value,
        now.effective_from,
        now.source,
        today,
        _email(conn, who),
    )
    return _save(request, who, conn, item, "regulatory.verified")
