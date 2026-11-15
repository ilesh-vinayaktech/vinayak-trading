# ruff: noqa: E501
"""Research intelligence (plan.md phases 1 to 5), read-only: what the feature registry, alpha discovery, the strategy factory, research memory, strategy health and capital
allocation have recorded. Nothing here writes, runs a job or places an order; every number is read from a table those parts already fill.

Callers: frontend/app/research/intelligence/page.tsx and tests/integration/test_intel_routes.py. Default permission for GET (research:read)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from algo.api.security import WConn
from algo.jobs import progress as job_progress
from algo.learning import memory

router = APIRouter(prefix="/api/intel", tags=["intelligence"])
STALLED_AFTER_S = (
    600  # a running job that has said nothing for this long is flagged as possibly stuck
)


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


@router.get("/progress")
def progress(request: Request, conn: WConn, limit: int = Query(10, ge=1, le=50)) -> dict[str, Any]:
    """What the long jobs are doing now: running ones first, then the latest finished. `alive` says whether the job's process still exists; `stalled` that a running job has been quiet too long."""
    now = request.app.state.portal.clock.now()
    jobs = []
    for r in job_progress.recent(conn, limit):
        running = r["status"] == "RUNNING"
        quiet = int((now - r["updated_at"]).total_seconds())
        jobs.append(
            {
                "id": r["run_id"], "job": r["job"], "label": r["label"], "status": r["status"], "done": r["done"], "total": r["total"],
                "phase": r["phase"], "message": r["message"], "started_at": r["started_at"].isoformat(), "updated_at": r["updated_at"].isoformat(),
                "elapsed_s": int(((r["finished_at"] or now) - r["started_at"]).total_seconds()),
                "quiet_s": quiet if running else None,
                "alive": job_progress.alive(r["pid"]) if running else None,
                "stalled": running and (quiet > STALLED_AFTER_S or not job_progress.alive(r["pid"])),
            }
        )  # fmt: skip
    return {"jobs": jobs}


def _stage(
    key: str,
    title: str,
    unit: str,
    entered: int,
    passed: int,
    dropped: list[tuple[str, int]],
    note: str,
    connected: bool = True,
) -> dict[str, Any]:
    return {
        "key": key, "title": title, "unit": unit, "entered": entered, "passed": passed, "connected": connected, "note": note,
        "dropped": [{"reason": r, "count": n} for r, n in dropped if n > 0],
    }  # fmt: skip


@router.get("/funnel")
def funnel(conn: WConn) -> dict[str, Any]:
    """The research pipeline as a funnel: for each stage how many went in, how many moved on, and how many were dropped and why. Every number is a count of recorded rows."""

    def one(sql: str) -> int:
        return _one(conn, sql)

    features = one("SELECT count(*) FROM feature_definition")
    latest = "(SELECT status FROM feature_status WHERE feature_id = d.feature_id ORDER BY status_id DESC LIMIT 1)"
    usable = one(f"SELECT count(*) FROM feature_definition d WHERE {latest} = 'USABLE'")  # noqa: S608 - fixed fragment
    blocked = one(f"SELECT count(*) FROM feature_definition d WHERE {latest} = 'BLOCKED'")  # noqa: S608
    failed_check = one(
        f"SELECT count(*) FROM feature_definition d WHERE {latest} = 'DRAFT' AND COALESCE((SELECT NOT passed FROM feature_validation v WHERE v.feature_id = d.feature_id ORDER BY report_id DESC LIMIT 1), FALSE)"  # noqa: S608
    )
    waiting = features - usable - blocked - failed_check
    tests = conn.execute(
        "SELECT count(*), count(*) FILTER (WHERE research_status = 'CANDIDATE'),"
        " count(*) FILTER (WHERE research_status = 'REJECTED' AND (evidence->>'mean_ic' IS NULL OR evidence->>'p_adjusted' IS NULL)),"
        " count(*) FILTER (WHERE research_status = 'REJECTED' AND evidence->>'mean_ic' IS NOT NULL AND evidence->>'p_adjusted' IS NOT NULL AND abs((evidence->>'mean_ic')::float) < (evidence->>'min_abs_ic')::float)"
        " FROM alpha_hypothesis"
    ).fetchone()
    assert tests is not None
    total, candidates, no_result, too_small = (int(x) for x in tests)
    not_significant = total - candidates - no_result - too_small
    definitions = one("SELECT count(*) FROM strategy_definition")
    tested = one("SELECT count(DISTINCT (base_strategy_id, base_version)) FROM factory_experiment")
    trials = one("SELECT count(*) FROM factory_trial")
    done = one("SELECT count(*) FROM factory_trial WHERE status = 'DONE'")
    skipped = one("SELECT count(*) FROM factory_trial WHERE status = 'SKIPPED'")
    return {
        "stages": [
            _stage("features", "Features", "features", features, usable,
                   [("Failed validation", failed_check), ("Waiting to be validated", waiting), ("Blocked", blocked)],
                   "A feature must pass coverage, reproducibility and look-ahead checks before anything may use it."),
            _stage("alpha", "Alpha tests", "tests", total, candidates,
                   [("No result (too little data)", no_result), ("Effect too small to matter", too_small), ("Not significant after counting every test ever run", not_significant)],
                   "Each feature at each horizon is one test. A candidate means worth validating, never that it works."),
            _stage("definitions", "Strategy definitions", "definitions", definitions, tested, [("Not tried in an experiment yet", definitions - tested)],
                   "Registered strategy versions that an experiment has actually run."),
            _stage("trials", "Experiment trials", "trials", trials, done, [("Not a valid definition", skipped), ("Could not run", trials - done - skipped)],
                   "Every combination tried counts, finished or not, because the number of tries is what makes a result honest."),
            _stage("validation", "Validation gates", "strategies", 0, 0, [],
                   "Walk-forward, costs and the one-time holdout. Not yet linked to alpha candidates or strategy definitions.", connected=False),
            _stage("paper", "Paper trading", "strategies", 0, 0, [], "Strategies that passed validation and run on a paper account. Nothing reaches here automatically yet.", connected=False),
        ]
    }  # fmt: skip
