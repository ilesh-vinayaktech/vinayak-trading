# ruff: noqa: E501
"""The bird's-eye view of research: every strategy definition and how far it got (development, inner holdout, outer holdout, paper), where it stopped and why, and what
it returned in the stages whose figures research may see. Outer-holdout verdicts are owner-only (`holdout:read`, policy v3 section 5) and carry no figures."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from algo.api import holdout_routes
from algo.api.security import CurrentUser, WConn
from algo.paper import definitions
from algo.research.code_identity import git_state

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])
INNER_DAYS = 252  # trading days a year, to turn the inner holdout's total return into a yearly one


def _cagr(total_return: float | None, days: float | None) -> float | None:
    if total_return is None or not days or total_return <= -1:
        return None
    return float((1 + total_return) ** (INNER_DAYS / days) - 1)


def failed(gates: list[dict[str, Any]]) -> list[str]:
    return [g["name"] for g in gates if g["status"] != "PASS"]


def summarise(
    dev: dict[str, Any] | None,
    inner: dict[str, Any] | None,
    outer: dict[str, Any] | None,
    paper: str | None,
    running: str | None,
) -> dict[str, str]:
    """Where a strategy stands: the stage it is at (`stage`), whether it stopped (`outcome`: ready, stopped, waiting, running) and a one-line reason, from what each stage found."""
    if dev is None:
        return {
            "stage": "development",
            "outcome": "running" if running else "waiting",
            "why": running or "Development has not run yet.",
        }
    if not dev["passed"]:
        return {
            "stage": "development",
            "outcome": "stopped",
            "why": "Failed development: " + ", ".join(dev["failed"]) + ".",
        }
    if outer is not None:
        if outer["overall"] == "PASS" and paper == "ready":
            return {
                "stage": "paper",
                "outcome": "ready",
                "why": "Passed development and both holdouts. Ready for paper trading.",
            }
        if outer["overall"] == "PASS":
            return {
                "stage": "outer",
                "outcome": "waiting",
                "why": "Passed the outer holdout but is not yet allowed for paper trading.",
            }
        if outer["overall"] == "FAIL":
            return {
                "stage": "outer",
                "outcome": "stopped",
                "why": "Failed the outer holdout (2025-2026): "
                + ", ".join(c["gate"] for c in outer["checks"] if c["verdict"] == "FAIL")
                + ".",
            }
        return {
            "stage": "outer",
            "outcome": "waiting",
            "why": "Outer holdout has checks without evidence.",
        }
    if inner is None:
        return {
            "stage": "inner",
            "outcome": "running" if running else "waiting",
            "why": running or "Passed development. The inner holdout (2023-2024) has not run yet.",
        }
    if not inner["passed"]:
        return {
            "stage": "inner",
            "outcome": "stopped",
            "why": "Failed the inner holdout (2023-2024): "
            + ", ".join(inner["failed"])
            + ". Not yet submitted to the outer holdout.",
        }
    return {
        "stage": "inner",
        "outcome": "waiting",
        "why": "Passed the inner holdout. Waiting to be submitted to the outer holdout.",
    }


def _dev(conn: Any, exp: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT v.passed, v.gates, v.evidence, r.metrics, r.config->>'start', r.config->>'end' FROM validation_report v JOIN backtest_run r USING (run_id)"
        " WHERE v.experiment_id=%s ORDER BY v.report_id DESC LIMIT 1",
        (exp,),
    ).fetchone()
    if row is None:
        return None
    passed, gates, ev, m, start, end = row
    return {
        "passed": passed, "failed": failed(gates), "oos_sharpe": ev.get("oos_sharpe"), "benchmark_sharpe": ev.get("benchmark_sharpe"),
        "cagr": m.get("cagr"), "total_return": m.get("total_return"), "sharpe": m.get("sharpe"), "max_drawdown": m.get("max_drawdown"), "window": [start, end],
    }  # fmt: skip


def _inner(conn: Any, exp: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT passed, gates, evidence, refs->'window' FROM study_holdout WHERE experiment_id=%s",
        (exp,),
    ).fetchone()
    if row is None:
        return None
    passed, gates, ev, window = row
    return {
        "passed": passed, "failed": failed(gates), "total_return": ev.get("total_return"), "cagr": _cagr(ev.get("total_return"), ev.get("days")),
        "sharpe": ev.get("sharpe"), "max_drawdown": ev.get("max_drawdown"), "benchmark_sharpe": ev.get("benchmark_sharpe"), "window": window,
    }  # fmt: skip


@router.get("")
def overview(who: CurrentUser, conn: WConn) -> dict[str, Any]:
    owner = "holdout:read" in who.permissions
    outer = {r["candidate"]: r for r in holdout_routes._results(conn)} if owner else {}
    paper = {d["strategy_id"]: d["state"] for d in definitions.candidates(conn)}
    rows = []
    for exp, name, family in conn.execute(
        "SELECT DISTINCT ON (key) experiment_id, key, family FROM (SELECT e.experiment_id, coalesce(e.study->'spec'->'definition'->>'strategy_id', e.name) AS key, f.name AS family"
        " FROM experiment e LEFT JOIN research_family f USING (family_id) WHERE e.study IS NOT NULL) x ORDER BY key, experiment_id DESC"
    ).fetchall():
        run = conn.execute(
            "SELECT kind, status FROM study_run WHERE experiment_id=%s ORDER BY run_id DESC LIMIT 1",
            (exp,),
        ).fetchone()
        running = f"{run[0]} {run[1].lower()}" if run and run[1] in ("QUEUED", "RUNNING") else None
        dev, inner, out = _dev(conn, exp), _inner(conn, exp), outer.get(f"study-{exp}")
        rows.append({
            "experiment_id": exp, "name": name, "family": family, "development": dev, "inner": inner, "outer": out, "paper": paper.get(name),
            **summarise(dev, inner, out, paper.get(name), running),
        })  # fmt: skip
    return {"rows": rows, "outer_visible": owner, "code_dirty": git_state()[1]}


@router.get("/unrun")
def unrun(who: CurrentUser, conn: WConn) -> dict[str, Any]:
    """Registered studies that have never been run, grouped by research family: what the Run popup offers."""
    fams: dict[int, dict[str, Any]] = {}
    for exp, name, strategy, fid, fname in conn.execute(
        "SELECT e.experiment_id, e.name, e.strategy_id, f.family_id, f.name FROM experiment e JOIN research_family f USING (family_id)"
        " WHERE e.study IS NOT NULL AND NOT EXISTS (SELECT 1 FROM study_run r WHERE r.experiment_id = e.experiment_id) ORDER BY f.family_id, e.experiment_id"
    ).fetchall():
        fams.setdefault(fid, {"family_id": fid, "name": fname, "studies": []})["studies"].append(
            {"experiment_id": exp, "name": name, "strategy_id": strategy}
        )
    return {"families": list(fams.values())}
