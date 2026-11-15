# ruff: noqa: E501
"""Research intelligence (plan.md phases 1 to 5), read-only: what the feature registry, alpha discovery, the strategy factory, research memory, strategy health and capital
allocation have recorded. Nothing here writes, runs a job or places an order; every number is read from a table those parts already fill.

Callers: frontend/app/research/intelligence/page.tsx and tests/integration/test_intel_routes.py. Default permission for GET (research:read)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from algo.api.security import WConn
from algo.learning import memory

router = APIRouter(prefix="/api/intel", tags=["intelligence"])


def _counts(conn: Any, sql: str) -> dict[str, int]:
    return {str(k): int(n) for k, n in conn.execute(sql).fetchall()}


def _one(conn: Any, sql: str) -> int:
    return int(conn.execute(sql).fetchone()[0])


@router.get("/overview")
def overview(conn: WConn) -> dict[str, Any]:
    features = _counts(
        conn,
        "SELECT s.status, count(*) FROM feature_definition d JOIN LATERAL"
        " (SELECT status FROM feature_status WHERE feature_id = d.feature_id ORDER BY status_id DESC LIMIT 1) s ON TRUE GROUP BY 1",
    )
    alpha = _counts(conn, "SELECT research_status, count(*) FROM alpha_hypothesis GROUP BY 1")
    health = conn.execute(
        "SELECT DISTINCT ON (scope) scope, status, detail, run_at FROM dq_result WHERE check_name = 'degradation' ORDER BY scope, run_at DESC"
    ).fetchall()
    last = conn.execute(
        "SELECT recommendation_id, method, weights, cash, notes, created_by, created_at FROM allocation_recommendation ORDER BY recommendation_id DESC LIMIT 1"
    ).fetchone()
    return {
        "features": {"by_status": features},
        "alpha": {"tests_ever_run": sum(alpha.values()), "by_status": alpha},
        "factory": {
            "definitions": _one(conn, "SELECT count(*) FROM strategy_definition"),
            "experiments": _one(conn, "SELECT count(*) FROM factory_experiment"),
            "trials": _one(conn, "SELECT count(*) FROM factory_trial"),
        },
        "notes": {"total": _one(conn, "SELECT count(*) FROM research_note")},
        "health": [
            {"scope": r[0], "status": r[1], "detail": r[2], "at": r[3].isoformat()} for r in health
        ],
        "allocation": None
        if last is None
        else {
            "id": last[0],
            "method": last[1],
            "weights": last[2],
            "cash": last[3],
            "notes": last[4],
            "by": last[5],
            "at": last[6].isoformat(),
        },
    }


@router.get("/alpha")
def alpha(
    conn: WConn,
    status: str | None = Query(None, pattern="^(CANDIDATE|REJECTED)$"),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    where, args = ("WHERE research_status = %s", [status]) if status else ("", [])
    rows = conn.execute(
        f"SELECT hypothesis_id, batch_id, feature_name, feature_version, horizon_days, research_status, evidence, created_at FROM alpha_hypothesis {where} ORDER BY hypothesis_id DESC LIMIT %s",  # noqa: S608 - fixed fragments only
        (*args, limit),
    ).fetchall()
    return {
        "hypotheses": [
            {
                "id": r[0], "batch": r[1], "feature": r[2], "version": r[3], "horizon": r[4], "status": r[5],
                "mean_ic": r[6].get("mean_ic"), "icir": r[6].get("icir"), "p_adjusted": r[6].get("p_adjusted"),
                "direction": r[6].get("direction"), "sample_days": r[6].get("sample_days"), "at": r[7].isoformat(),
            }
            for r in rows
        ]
    }  # fmt: skip


@router.get("/notes")
def notes(
    conn: WConn,
    q: str | None = Query(None, max_length=200),
    kind: str | None = Query(None, pattern="^(FINDING|FAILURE|DECISION|LESSON)$"),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    found = memory.search(conn, text=q, kind=kind, limit=limit)
    return {
        "notes": [
            {"id": n.note_id, "kind": n.kind, "subject": n.subject, "body": n.body, "tags": n.tags, "by": n.created_by, "at": n.created_at.isoformat()}
            for n in found
        ]
    }  # fmt: skip


@router.get("/allocations")
def allocations(conn: WConn, limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT recommendation_id, method, weights, cash, notes, risk_contribution, created_by, created_at FROM allocation_recommendation ORDER BY recommendation_id DESC LIMIT %s",
        (limit,),
    ).fetchall()
    return {
        "allocations": [
            {"id": r[0], "method": r[1], "weights": r[2], "cash": r[3], "notes": r[4], "risk_contribution": r[5], "by": r[6], "at": r[7].isoformat()}
            for r in rows
        ]
    }  # fmt: skip
