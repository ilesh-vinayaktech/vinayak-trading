# ruff: noqa: E501
"""The holdout ledger for the owner (docs/holdout-policy-v3.md section 10 step 6): the slot budget, the batch history, the cutoff snapshot's plan and a confirmation before a batch is frozen.

Owner only (`holdout:read`). It shows state, counts and each strategy's pass/fail per check (read through the promotion path's reader, section 5), never a p-value or a figure."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from algo.api.security import CurrentUser, WConn
from algo.portal import audit
from algo.promotion import verdicts as pv
from algo.research import holdout_batch, holdout_cutoff

router = APIRouter(prefix="/api/holdout", tags=["holdout"])
WARNINGS = (
    "These dates (2025-01-01 to 2026-11-13) are a repeatedly accessed validation set, not an untouched holdout, once Batch 1 has been read. Only forward sessions after each strategy was locked are untouched.",
    "A FAIL means not proven here, not no edge. The 5% family-wise claim holds only if every strategy was fixed independently of the holdout observations and every p-value is valid; it is never an unconditional guarantee.",
)


def _st(request: Request) -> Any:
    return request.app.state.portal


class Freeze(BaseModel):
    confirm: bool = False


class Submit(BaseModel):
    candidates: list[str] = Field(min_length=1, max_length=holdout_batch.BUDGET)
    declaration: str = ""
    confirm: bool = False


def _results(conn: Any) -> list[dict[str, Any]]:
    """Each evaluated strategy's checks. A check that had no evidence and was completed later (holdout_supplement) shows the later verdict, marked `later`;
    the promotion path counts a completed check by its later verdict."""
    try:
        original = pv.read_verdicts(conn)
    except holdout_batch.BatchError:  # no consumed batch yet
        return []
    later = {(c, g): v for c, g, v in pv.read_supplements(conn)}
    names = dict(
        conn.execute(
            "SELECT 'study-' || experiment_id, study->'spec'->'definition'->>'strategy_id' FROM experiment WHERE study->'spec'->'definition'->>'strategy_id' IS NOT NULL"
        ).fetchall()
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for cand, gate, v in original:
        done = later.get((cand, gate))
        out.setdefault(cand, []).append(
            {"gate": gate, "verdict": done or v, "later": done is not None}
        )
    rows = []
    for cand, checks in out.items():
        got = {c["verdict"] for c in checks}
        overall = (
            "FAIL"
            if "FAIL" in got
            else "PASS"
            if got <= {"PASS", "NOT_APPLICABLE"} and "PASS" in got
            else "INCOMPLETE"
        )
        rows.append({"name": names.get(cand, cand), "overall": overall, "checks": checks})
    return sorted(rows, key=lambda r: r["name"])


def _eligible(conn: Any) -> list[dict[str, Any]]:
    """Strategies that passed development from clean code and have not used a slot, with their inner-holdout (2023-2024) outcome: what the owner may submit."""
    out = []
    for c in holdout_cutoff.snapshot(conn)["candidates"]:
        if c["development_verdict"] != "PASSED" or c["slot"] or c["excluded_reason"]:
            continue
        sid, ver = c["candidate_id"].split("@")
        if holdout_cutoff._clean_passed_study(conn, sid, int(ver)) is None:
            continue
        h = conn.execute(
            "SELECT passed, (evidence->>'sharpe')::float, (evidence->>'benchmark_sharpe')::float FROM study_holdout WHERE experiment_id=%s",
            (c["experiment_id"],),
        ).fetchone()
        out.append({
            "candidate_id": c["candidate_id"],
            "inner": None if h is None else {"passed": h[0], "sharpe": h[1], "index_sharpe": h[2]},
        })  # fmt: skip
    return out


@router.get("")
def overview(who: CurrentUser, conn: WConn) -> dict[str, Any]:
    consumed, reserved, left = holdout_batch.slots(conn)
    batches = [
        {"batch_id": r[0], "state": r[1], "candidates": r[2], "frozen_at": r[3].isoformat() if r[3] else None, "first_read": r[4] is not None, "members": r[5] or []}
        for r in conn.execute(
            "SELECT b.batch_id, b.state, (SELECT count(*) FROM holdout_candidate c WHERE c.batch_id = b.batch_id AND c.state <> 'RELEASED'), b.frozen_at, b.first_read_at,"
            " (SELECT array_agg(coalesce(e.study->'spec'->'definition'->>'strategy_id', c.candidate_id) ORDER BY c.candidate_id) FROM holdout_candidate c"
            "  LEFT JOIN experiment e ON c.candidate_id = 'study-' || e.experiment_id WHERE c.batch_id = b.batch_id AND c.state <> 'RELEASED')"
            " FROM holdout_batch b ORDER BY b.batch_id"
        ).fetchall()
    ]  # fmt: skip
    cut = conn.execute(
        "SELECT cutoff_id, kind, fired_at FROM holdout_cutoff ORDER BY cutoff_id DESC LIMIT 1"
    ).fetchone()
    plan = None
    if cut is not None:
        p = holdout_cutoff.plan(conn, cut[0])
        plan = {
            "members": list(p.members),
            "carry_over": list(p.carry_over),
            "excluded": p.excluded,
            "problems": list(p.problems),
            "can_freeze": p.can_freeze,
        }
    return {
        "budget": holdout_batch.BUDGET, "consumed": consumed, "reserved": reserved, "left": left,
        "previously_tested": consumed, "batches": batches, "eligible": _eligible(conn), "results": _results(conn), "warnings": list(WARNINGS),
        "audit_signed": conn.execute("SELECT 1 FROM holdout_audit LIMIT 1").fetchone() is not None,
        "cutoff": None if cut is None else {"cutoff_id": cut[0], "kind": cut[1], "fired_at": cut[2].isoformat(), "plan": plan},
    }  # fmt: skip


@router.post("/cutoffs/{cutoff_id}/freeze")
def freeze(
    cutoff_id: int, body: Freeze, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, Any]:
    """Freeze the batch of this cutoff. Needs an explicit confirmation: it reserves slots for good and commits the seeds."""
    if not body.confirm:
        raise HTTPException(422, "confirm the freeze: it reserves the slots and commits the seeds")
    try:
        batch_id = holdout_cutoff.freeze_batch(
            conn,
            cutoff_id,
            str(who.session.user_id),
            _st(request).clock.now(),
        )
    except holdout_cutoff.CutoffError as e:
        raise HTTPException(404, str(e)) from e
    except holdout_batch.BatchError as e:
        raise HTTPException(409, str(e)) from e
    if batch_id is None:
        raise HTTPException(
            409,
            "the plan does not allow a batch yet: "
            + "; ".join(holdout_cutoff.plan(conn, cutoff_id).problems),
        )
    audit.record(
        conn,
        now=_st(request).clock.now(),
        action="holdout.batch_frozen",
        actor_user_id=who.session.user_id,
        target_type="holdout_batch",
        target_id=str(batch_id),
        detail={"cutoff_id": cutoff_id},
    )
    return {"ok": True, "batch_id": batch_id}


@router.post("/submit")
def submit(body: Submit, request: Request, who: CurrentUser, conn: WConn) -> dict[str, Any]:
    """Freeze a batch of strategies that passed development, as the 19 went. Needs the confirmation and the owner's one-line declaration; it reserves slots and commits seeds."""
    if not body.confirm:
        raise HTTPException(422, "confirm the submit: it reserves the slots and commits the seeds")
    try:
        batch_id = holdout_cutoff.submit(
            conn,
            body.candidates,
            body.declaration,
            str(who.session.user_id),
            _st(request).clock.now(),
        )
    except holdout_batch.BatchError as e:  # CutoffError is a BatchError
        raise HTTPException(409, str(e)) from e
    audit.record(
        conn,
        now=_st(request).clock.now(),
        action="holdout.batch_submitted",
        actor_user_id=who.session.user_id,
        target_type="holdout_batch",
        target_id=str(batch_id),
        detail={"candidates": body.candidates},
    )
    return {"ok": True, "batch_id": batch_id}
