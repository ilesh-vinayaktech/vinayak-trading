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
from algo.research.study import StudySpec, default_thresholds
from algo.research.study_store import register_study

GRID = {
    "max_positions": [10, 20, 30],
    "exit_share": [30, 50, 70],
}  # entry_share is left out: with hundreds of stocks a 10-30% entry share never binds below max_positions, so it would only add identical trials


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
) -> StudySpec:
    defn = registry.get(conn, strategy_id, version)
    return StudySpec.model_validate(
        {
            "name": f"{strategy_id} v{version} {start.year}-{holdout_start.year - 1}",
            "hypothesis": f"{defn.description} Tested over a counted grid of its own numbers; it must beat buy-and-hold after 2x costs, out of sample.",
            "strategy_id": "dsl",
            "definition": defn.canonical(),
            "grid": GRID,
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
        }
    )


def register(conn: psycopg.Connection, owner: UUID, spec: StudySpec, now: datetime) -> int:
    return register_study(conn, owner, spec, now)
