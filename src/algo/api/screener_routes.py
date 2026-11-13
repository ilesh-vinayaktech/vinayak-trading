# ruff: noqa: E501
"""Stock screener: the fields and ready-made screens (`meta`) and running a screen (`run`). Read-only; research:read."""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from algo.api.security import WConn
from algo.screener import engine, snapshot
from algo.screener.presets import BY_ID, PRESETS

router = APIRouter(prefix="/api/screener", tags=["screener"])
Q4 = Decimal("0.0001")


class ConditionBody(BaseModel):
    field: str
    op: str
    value: Any


class RunBody(BaseModel):
    preset: str | None = None
    conditions: list[ConditionBody] = Field(default_factory=list, max_length=20)
    match: Literal["all", "any"] = "all"
    sort: str | None = None
    descending: bool = True
    limit: int = Field(default=100, ge=1, le=500)


def _json(v: Any) -> Any:
    return str(v.quantize(Q4)) if isinstance(v, Decimal) else v


@router.get("/meta")
def meta() -> dict[str, Any]:
    return {
        "fields": [asdict(f) for f in engine.FIELDS.values()],
        "presets": [
            {**asdict(p), "conditions": [asdict(c) for c in p.conditions]} for p in PRESETS
        ],
    }


@router.post("/run")
def run(body: RunBody, conn: WConn) -> dict[str, Any]:
    conds = [engine.Condition(c.field, c.op, c.value) for c in body.conditions]
    sort, desc = body.sort, body.descending
    if body.preset is not None:
        p = BY_ID.get(body.preset)
        if p is None:
            raise HTTPException(404, f"no screen {body.preset!r}")
        conds, sort, desc = (
            list(p.conditions),
            sort or p.sort,
            p.descending if body.sort is None else desc,
        )
    table = snapshot.build(conn)
    try:
        rows, total = engine.run(
            table,
            conds,
            match=body.match,
            sort=sort,
            descending=desc,
            limit=body.limit,
        )
    except engine.ScreenError as e:
        raise HTTPException(422, str(e)) from e
    return {
        "total": total,
        "sort": sort,
        "as_of": max(
            (r["as_of"] for r in table), default=None
        ),  # the last trading day the figures are from
        "rows": [{k: _json(v) for k, v in r.items()} for r in rows],
    }
