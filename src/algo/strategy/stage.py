# ruff: noqa: E501
"""Where a saved strategy stands: RESEARCH, PAPER or LIVE, and the rules for moving it.

- RESEARCH to PAPER needs only a reason. The owner waived the validation requirement for paper trading (it moves no money
  and is labelled UNVALIDATED everywhere), and the waiver is written into the record so it is never mistaken for a pass.
- PAPER to LIVE is gated in code: a backtest run of THIS strategy with THESE settings that has no promotion blocker
  (strict data, modelled corporate actions, reconciled ledger, verified costs, realistic slippage, and a passing
  validation report against confirmed thresholds). RESEARCH cannot jump to LIVE.
- Moving down is always allowed.
Every move is an append-only row with who approved it and when (migration 048)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from algo.backtest import store
from algo.core.clock import require_utc
from algo.strategy.lifecycle import promotion_blockers

STAGES = ("RESEARCH", "PAPER", "LIVE")
PAPER_WAIVER = "entered paper under the owner's waiver: the strategy is unvalidated research"


class StageError(ValueError):
    pass


def current(conn: psycopg.Connection, config_id: UUID) -> str:
    row = conn.execute(
        "SELECT to_stage FROM strategy_stage_change WHERE config_id=%s ORDER BY change_id DESC LIMIT 1",
        (config_id,),
    ).fetchone()
    return "RESEARCH" if row is None else str(row[0])


def history(conn: psycopg.Connection, config_id: UUID) -> list[dict[str, Any]]:
    keys = ("change_id", "from_stage", "to_stage", "approver", "at", "run_id", "reason", "waived")
    return [
        dict(zip(keys, r, strict=True))
        for r in conn.execute(
            "SELECT c.change_id, c.from_stage, c.to_stage, u.display_name, c.at, c.run_id, c.reason, c.waived"
            " FROM strategy_stage_change c JOIN portal_user u ON u.user_id = c.approver_user_id"
            " WHERE c.config_id=%s ORDER BY c.change_id",
            (config_id,),
        )
    ]


def _gate_live(
    conn: psycopg.Connection, config: tuple[str, dict[str, Any]], run_id: int | None
) -> None:
    if run_id is None:
        raise StageError("going live needs a backtest run that justifies it")
    row = conn.execute(
        "SELECT strategy_id, params FROM backtest_run WHERE run_id=%s", (run_id,)
    ).fetchone()
    if row is None:
        raise StageError(f"there is no backtest run {run_id}")
    strategy_id, params = config
    if row[0] != strategy_id:
        raise StageError(f"run {run_id} is of a different strategy ({row[0]}, not {strategy_id})")
    if any(row[1].get(k) != v for k, v in params.items()):
        raise StageError(f"run {run_id} used different settings from this strategy's")
    blockers = promotion_blockers(store.summary(conn, run_id))
    if blockers:
        raise StageError("not eligible to go live: " + "; ".join(blockers))


def change(
    conn: psycopg.Connection,
    config_id: UUID,
    to_stage: str,
    approver: UUID,
    now: datetime,
    *,
    reason: str,
    run_id: int | None = None,
) -> int:
    """Move a strategy to `to_stage`, or raise StageError saying why not. Returns the change id."""
    if to_stage not in STAGES:
        raise StageError(f"unknown stage {to_stage!r}")
    if not reason.strip():
        raise StageError("say why: a reason is required")
    cfg = conn.execute(
        "SELECT strategy_id, params FROM strategy_config WHERE config_id=%s", (config_id,)
    ).fetchone()
    if cfg is None:
        raise StageError("no such strategy")
    now_at = current(conn, config_id)
    if to_stage == now_at:
        raise StageError(f"the strategy is already in {now_at}")
    up = STAGES.index(to_stage) > STAGES.index(now_at)
    if up and STAGES.index(to_stage) - STAGES.index(now_at) > 1:
        raise StageError("a strategy goes live through paper trading first")
    waived: list[str] = []
    if up and to_stage == "PAPER":
        waived = [PAPER_WAIVER]
    elif up:
        _gate_live(conn, (cfg[0], cfg[1]), run_id)
    row = conn.execute(
        "INSERT INTO strategy_stage_change (config_id, from_stage, to_stage, approver_user_id, at, run_id, reason, waived)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING change_id",
        (
            config_id,
            now_at,
            to_stage,
            approver,
            require_utc(now),
            run_id,
            reason.strip(),
            Jsonb(waived),
        ),
    ).fetchone()
    assert row is not None
    return int(row[0])
