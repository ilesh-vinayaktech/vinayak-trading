# ruff: noqa: E501
"""Put a registered strategy definition into the study machinery (plan.md sections 7-8): the same experiments, walk-forward, cost stress and one-time holdout as any coded strategy.

Callers: scripts/register_definition_study.py and tests/integration/test_study_runner.py. Nothing similar exists (generate.py only writes definitions).
User's instruction: "Experiments and validation: the experiment runner exists, but nothing links it to the validation gates".

The grid is small and counted: every combination is a trial, so trying more only raises the bar (deflated Sharpe). It varies the definition's own numbers (entry share, position count), never its features."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import psycopg

from algo.factory import registry
from algo.factory.dsl import PERCENT_OPS, StrategyDef
from algo.research import study_jobs
from algo.research.study import StudySpec, default_thresholds
from algo.research.study_store import register_study

STOP = Decimal("0.02")
COOLDOWN_DAYS = 5
GRID = {
    "max_positions": [10, 20, 30],
    "exit_share": [30, 50, 70],
}  # entry_share is left out: with hundreds of stocks a 10-30% entry share never binds below max_positions, so it would only add identical trials


def own_setting(defn: StrategyDef) -> dict[str, int]:
    """The definition's OWN written-down numbers (its position count and the share it sells at), the setting pre-registered for a single-configuration study: read from the definition, never chosen from results."""
    exit_share = next(int(c.value) for c in defn.exit.conditions() if c.op in PERCENT_OPS)
    return {"max_positions": defn.position.max_positions, "exit_share": exit_share}


def grid_around(own: dict[str, int]) -> dict[str, list[int | float]]:
    """The robustness grid: the definition's own setting and a step either side, so the neighbours can be compared with it."""
    p, e = own["max_positions"], own["exit_share"]
    return {
        "max_positions": [max(5, p - 10), p, p + 10],
        "exit_share": [max(5, e - 20), e, min(95, e + 20)],
    }


def spec_for(
    conn: psycopg.Connection,
    strategy_id: str,
    version: int,
    *,
    family_id: int,
    start: date,
    end: date,
    holdout_start: date,
    capital: Decimal = Decimal(100000),
    broker: str = "zerodha",
    fixed: bool = False,
) -> StudySpec:
    """`fixed`: a single-configuration study of the definition's own setting (nothing is chosen from results; the grid around it only checks its neighbours)."""
    defn = registry.get(conn, strategy_id, version)
    own = own_setting(defn) if fixed else None
    return StudySpec.model_validate(
        {
            "name": f"{strategy_id} v{version} {start.year}-{holdout_start.year - 1} stop{int(STOP * 100)}{' fixed' if fixed else ''}",
            "hypothesis": f"{defn.description} Tested over a counted grid of its own numbers; it must beat buy-and-hold after 2x costs, out of sample.",
            "strategy_id": "dsl",
            "definition": defn.canonical(),
            "grid": grid_around(own) if own else GRID,
            "universe": {
                "segments": ["large", "mid"],
                "min_history_sessions": max(252, defn.warmup_bars() + 10),
            },
            "start": start.isoformat(),
            "end": end.isoformat(),
            "holdout_start": holdout_start.isoformat(),
            "capital": str(capital),
            "broker": broker,
            "thresholds": default_thresholds(),
            "family_id": family_id,
            "accept_survivorship_bias": True,
            "fixed": own,
            "trade_stop": str(
                STOP
            ),  # the paper account's per-trade stop and cooldown, so the validated strategy is the one that trades
            "stop_cooldown_days": COOLDOWN_DAYS,
        }
    )


class ReplacementRefused(ValueError):
    pass


def register(conn: psycopg.Connection, owner: UUID, spec: StudySpec, now: datetime) -> int:
    """Register the study. A single-configuration study of a definition whose earlier single-configuration study (same window and stop) already has a verdict must use the SAME setting: the
    robustness grid is never allowed to pick a replacement after the primary setting fails, which would bring the selection problem back under another name."""
    if spec.fixed is not None and spec.definition:
        d = spec.definition
        rows = conn.execute(
            "SELECT e.name, e.study->'spec'->'fixed' FROM experiment e WHERE e.strategy_id = 'dsl' AND e.study->'spec'->'fixed' IS NOT NULL AND e.study->'spec'->'fixed' <> 'null'::jsonb"
            " AND e.study->'spec'->'definition'->>'strategy_id' = %s AND (e.study->'spec'->'definition'->>'version')::int = %s"
            " AND e.study->'spec'->>'start' = %s AND e.study->'spec'->>'end' = %s AND COALESCE(e.study->'spec'->>'trade_stop', '') = %s"
            " AND EXISTS (SELECT 1 FROM validation_report r WHERE r.experiment_id = e.experiment_id)",
            (
                d["strategy_id"],
                int(d["version"]),
                spec.start.isoformat(),
                spec.end.isoformat(),
                "" if spec.trade_stop is None else str(spec.trade_stop),
            ),
        ).fetchall()
        for name, earlier in rows:
            if {k: int(v) for k, v in earlier.items()} != {
                k: int(v) for k, v in spec.fixed.items()
            }:
                raise ReplacementRefused(
                    f"{name} already has a verdict for {earlier}: a different fixed setting {spec.fixed} cannot be chosen after it (the grid is a check, not a menu)"
                )
    return register_study(conn, owner, spec, now)


WINDOW = (
    date(2016, 1, 1),
    date(2024, 12, 31),
    date(2023, 1, 1),
)  # research start, end of the study's range, first day of the inner holdout (2025+ is the global holdout)


def start(
    conn: psycopg.Connection,
    owner: UUID,
    strategy_id: str,
    version: int,
    now: datetime,
    *,
    family_id: int = 1,
) -> tuple[int, int]:
    """Make the definition's standard study (registered once: asking again finds it) and queue its trials. Returns (experiment id, run id); a run already queued or running is an error from the queue."""
    spec = spec_for(
        conn,
        strategy_id,
        version,
        family_id=family_id,
        start=WINDOW[0],
        end=WINDOW[1],
        holdout_start=WINDOW[2],
    )
    row = conn.execute(
        "SELECT experiment_id FROM experiment WHERE name = %s AND strategy_id = 'dsl'", (spec.name,)
    ).fetchone()
    eid = int(row[0]) if row else register(conn, owner, spec, now)
    return eid, study_jobs.enqueue(conn, eid, owner, now)
