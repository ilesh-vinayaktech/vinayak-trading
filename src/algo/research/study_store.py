# ruff: noqa: E501
"""Backtest studies in the database: register one (checked, pinned to the frozen data and the cost schedules, locked by
migration 045), list them, read one. A study is an experiment with its settings attached, so the trial counter, the
research-window rule and the one-time holdout of algo.backtest.validation.registry apply to it unchanged."""

from __future__ import annotations

import inspect
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg

from algo.backtest.validation import registry
from algo.data.benchmark import DEFAULT_BENCHMARK
from algo.live.market_calendar import IST
from algo.research import holdout_lock
from algo.research.code_identity import file_sha256, git_state
from algo.research.study import StudyError, StudySpec, check, combinations
from algo.strategies.registry import STRATEGIES

COLUMNS = "e.experiment_id, e.name, e.strategy_id, e.hypothesis, e.registered_at, e.holdout_opened_at, e.study, e.study_sha256, e.owner_user_id"


def _frozen_through(conn: psycopg.Connection) -> tuple[str, Any]:
    row = conn.execute(
        "SELECT freeze_id, through_date FROM data_freeze WHERE source='kite' ORDER BY taken_at DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise StudyError(
            "there is no frozen price history to register against: freeze it first (scripts/freeze_kite.py)"
        )
    return str(row[0]), row[1]


def register_study(conn: psycopg.Connection, owner: UUID, spec: StudySpec, now: datetime) -> int:
    """Check the study, pin it to the frozen data and the cost schedules in force, and register it. Returns its id."""
    lock = holdout_lock.require(conn)  # fails closed: no anchored lock, no registration
    check(spec, today=now.astimezone(IST).date(), development_end=lock.development_end)
    freeze_id, through = _frozen_through(conn)
    if spec.end > through:
        raise StudyError(
            f"the study ends {spec.end}, after the frozen history (which ends {through})"
        )
    costs = [
        {"schedule_id": r[0], "version": r[1], "broker": r[2], "product": r[3], "status": r[4],
         "valid_from": r[5].isoformat(), "valid_until": r[6].isoformat() if r[6] else None}
        for r in conn.execute(
            "SELECT schedule_id, version, broker, product, status, valid_from, valid_until FROM cost_schedule"
            " WHERE broker=%s AND product=%s ORDER BY valid_from, schedule_id",
            (spec.broker, spec.product),
        ).fetchall()
    ]  # fmt: skip
    if not costs:
        raise StudyError(f"there is no cost schedule for {spec.broker} {spec.product}")
    if (
        spec.benchmark != DEFAULT_BENCHMARK
        and conn.execute(
            "SELECT 1 FROM benchmark WHERE name=%s AND return_type='TOTAL_RETURN'",
            (spec.benchmark,),
        ).fetchone()
        is None
    ):
        raise StudyError(f"there is no total-return index called {spec.benchmark!r}")
    combos = combinations(spec)
    commit, dirty = git_state()
    strategy_file = inspect.getsourcefile(STRATEGIES[spec.strategy_id][0])
    study = {
        "spec": spec.model_dump(mode="json"),
        "combinations": combos,
        "data_freeze": {"id": freeze_id, "through": through.isoformat()},
        "cost_schedules": costs,
        # the study reads only what the database held at this moment, and records which code made it
        "known_at": now.isoformat(),
        "code": {
            "commit": commit, "dirty": dirty,
            "strategy_sha256": file_sha256(Path(strategy_file)) if strategy_file else "unknown",
        },
    }  # fmt: skip
    try:
        with conn.transaction():
            return registry.register(
                conn, name=spec.name, strategy_id=spec.strategy_id, hypothesis=spec.hypothesis, style="long_only",
                param_ranges={k: [min(v), max(v)] for k, v in spec.grid.items()},
                holdout=(spec.holdout_start, spec.end), now=now, study=study, owner_user_id=owner,
            )  # fmt: skip
    except psycopg.errors.UniqueViolation as e:
        raise StudyError(f"there is already a study called {spec.name!r}") from e


def _shown(conn: psycopg.Connection, row: tuple[Any, ...]) -> dict[str, Any]:
    eid, name, strategy_id, hypothesis, registered_at, opened, study, sha, owner = row
    return {
        "experiment_id": eid, "name": name, "strategy_id": strategy_id, "hypothesis": hypothesis,
        "registered_at": registered_at, "holdout_opened_at": opened, "spec": StudySpec.model_validate(study["spec"]).model_dump(mode="json"),
        "combinations": study["combinations"], "data_freeze": study["data_freeze"], "cost_schedules": study["cost_schedules"],
        "trials_planned": len(study["combinations"]), "trials_run": registry.trial_count(conn, eid),
        "sha256": sha, "owner_user_id": owner,
    }  # fmt: skip


def list_studies(conn: psycopg.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"SELECT {COLUMNS} FROM experiment e WHERE e.study IS NOT NULL ORDER BY e.registered_at DESC, e.experiment_id DESC"
    ).fetchall()
    return [_shown(conn, r) for r in rows]


def get_study(conn: psycopg.Connection, experiment_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {COLUMNS} FROM experiment e WHERE e.study IS NOT NULL AND e.experiment_id=%s",
        (experiment_id,),
    ).fetchone()
    return None if row is None else _shown(conn, row)
