# ruff: noqa: E501
"""Backtest studies: the choices the form offers, the registered studies, and registering a new one.

Everyone with research access reads them; people who may run strategies (strategy:own) register them. A registered study
is locked (migration 045): this API has no way to change or delete one, by design. Every registration is audited."""

from __future__ import annotations

from typing import Any, get_args

from fastapi import APIRouter, HTTPException, Request

from algo.api.security import CurrentUser, PortalSettings, WConn
from algo.portal import audit
from algo.research.study import (
    HOLDOUT_SHARE,
    MAX_TRIALS,
    SEGMENT_LISTS_FROM,
    SURVIVORSHIP_SAFE_FROM,
    Segment,
    StudyError,
    StudySpec,
    default_thresholds,
)
from algo.research.study_store import get_study, list_studies, register_study
from algo.strategies.registry import STRATEGIES

router = APIRouter(prefix="/api/studies", tags=["studies"])


def _params(params_cls: Any) -> list[dict[str, Any]]:
    return [
        {"name": name, "choices": list(get_args(f.annotation)) or None, "default": f.default}
        for name, f in params_cls.model_fields.items()
    ]


@router.get("/options")
def options(conn: WConn) -> dict[str, Any]:
    frozen = conn.execute(
        "SELECT max(through_date) FROM data_freeze WHERE source='kite'"
    ).fetchone()
    # only what a study can trade: delivery (a daily strategy holds overnight)
    products = list(get_args(StudySpec.model_fields["product"].annotation))
    brokers = conn.execute(
        "SELECT DISTINCT broker, product FROM cost_schedule WHERE product = ANY(%s)"
        " ORDER BY broker, product",
        (products,),
    ).fetchall()
    return {
        "strategies": [
            {"id": sid, "params": _params(params)} for sid, (_, params) in STRATEGIES.items()
        ],
        "segments": list(get_args(Segment)),
        "timeframes": ["1D"],
        "brokers": [{"broker": b, "product": p} for b, p in brokers],
        "frozen_through": frozen[0].isoformat() if frozen and frozen[0] else None,
        "survivorship_safe_from": SURVIVORSHIP_SAFE_FROM.isoformat(),
        "segment_lists_from": SEGMENT_LISTS_FROM.isoformat(),
        "max_trials": MAX_TRIALS,
        "holdout_share": list(HOLDOUT_SHARE),
        "thresholds": default_thresholds(),
    }


@router.get("")
def studies(conn: WConn) -> dict[str, Any]:
    return {"studies": list_studies(conn)}


@router.get("/{experiment_id}")
def study(experiment_id: int, conn: WConn) -> dict[str, Any]:
    found = get_study(conn, experiment_id)
    if found is None:
        raise HTTPException(404, "no such study")
    return found


@router.post("")
def register(body: StudySpec, request: Request, who: CurrentUser, conn: WConn) -> dict[str, int]:
    st: PortalSettings = request.app.state.portal
    now = st.clock.now()
    try:
        sid = register_study(conn, who.session.user_id, body, now)
    except StudyError as e:
        raise HTTPException(400, str(e)) from e
    audit.record(
        conn, now=now, action="study.registered", actor_user_id=who.session.user_id, target_type="experiment",
        target_id=str(sid), detail={"name": body.name, "strategy_id": body.strategy_id},
    )  # fmt: skip
    return {"experiment_id": sid}
