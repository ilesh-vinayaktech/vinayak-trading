# ruff: noqa: E501
"""The holdout ledger for the owner (docs/holdout-policy-v3.md section 10 step 6): the slot budget, the batch history, the cutoff snapshot's plan and a confirmation before a batch is frozen.

Owner only (`holdout:read`). It shows state and counts, never a verdict, a p-value or a figure: verdicts are read through the promotion path alone (section 5)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from algo.api.security import CurrentUser, WConn
from algo.portal import audit
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


@router.get("")
def overview(who: CurrentUser, conn: WConn) -> dict[str, Any]:
    consumed, reserved, left = holdout_batch.slots(conn)
    batches = [
        {"batch_id": r[0], "state": r[1], "candidates": r[2], "frozen_at": r[3].isoformat() if r[3] else None, "first_read": r[4] is not None}
        for r in conn.execute(
            "SELECT b.batch_id, b.state, (SELECT count(*) FROM holdout_candidate c WHERE c.batch_id = b.batch_id AND c.state <> 'RELEASED'), b.frozen_at, b.first_read_at"
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
        "previously_tested": consumed, "batches": batches, "warnings": list(WARNINGS),
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
