# ruff: noqa: E501
"""Strategy health check on a paper account (plan.md phase 4): is the paper account's recent behaviour consistent with the backtest it was approved on?

Callers: tests/integration/learning/test_health.py and scripts/strategy_health.py. Reads paper_equity and backtest_equity; writes one dq_result row per check.
User's instruction: "do as much as you can do yourself, keep taking things one by one from @TODO.md and @plan.md ... keep things finishing with test".
The reference is the stored backtest's days BEFORE the first paper day (the development period), the live series is the paper account's own equity. The verdict
is recorded and returned; it suspends nothing. dq_result only has PASS and FAIL, so DEGRADED is FAIL and every other status is PASS with its name (WATCH, INSUFFICIENT) at the
start of the detail: a caller that needs the nuance reads the returned Health."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import psycopg

from algo.core.clock import require_utc
from algo.learning import degradation


def check(
    conn: psycopg.Connection,
    user_id: UUID,
    run_id: int,
    *,
    now: datetime,
    thresholds: degradation.Thresholds | None = None,
) -> degradation.Health:
    now = require_utc(now)
    live: dict[date, Decimal] = dict(
        conn.execute("SELECT day, equity FROM paper_equity WHERE user_id=%s", (user_id,)).fetchall()
    )
    model: dict[date, Decimal] = dict(
        conn.execute(
            "SELECT day, equity FROM backtest_equity WHERE run_id=%s", (run_id,)
        ).fetchall()
    )
    if live:
        first = min(live)
        model = {d: v for d, v in model.items() if d < first}
    h = degradation.assess_equity(model, live, thresholds=thresholds)
    detail = f"{h.status}: " + (
        "; ".join(h.reasons) if h.reasons else f"z={h.evidence.get('z', float('nan')):.2f}"
    )
    conn.execute(
        "INSERT INTO dq_result (run_at, check_name, scope, subject, status, detail) VALUES (%s,'degradation',%s,NULL,%s,%s)",
        (
            now,
            f"paper {user_id} vs backtest run {run_id}",
            "FAIL" if h.status == "DEGRADED" else "PASS",
            detail,
        ),
    )
    return h
