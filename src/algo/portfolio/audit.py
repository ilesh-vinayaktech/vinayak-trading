# ruff: noqa: E501
"""Record every allocation recommendation (plan.md phase 5: 'allocation changes are auditable').

Callers: tests/integration/portfolio/test_audit.py. Schema: allocation_recommendation (migration 082, insert-only). User's instruction: "do as much as you can do
yourself, keep taking things one by one from @TODO.md and @plan.md ... keep things finishing with test".
`recommend_and_record` runs the allocator and stores the advice with the method, limits, volatility target, the health of every strategy and a hash of the exact
return series it was given (so the advice can be reproduced and an altered input is detectable). `changes_since_last` says what moved against the previous advice."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

from algo.core.clock import require_utc
from algo.portfolio import allocation


def inputs_hash(returns: Mapping[str, Sequence[float]], health: Mapping[str, str]) -> str:
    body = {
        "returns": {k: [repr(float(x)) for x in v] for k, v in sorted(returns.items())},
        "health": dict(sorted(health.items())),
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def recommend_and_record(
    conn: psycopg.Connection,
    returns: Mapping[str, Sequence[float]],
    health: Mapping[str, str],
    *,
    by: str,
    now: datetime,
    method: str = "RISK_PARITY",
    limits: allocation.Limits | None = None,
    target_vol: float | None = None,
) -> tuple[int, allocation.Allocation]:
    if not by.strip():
        raise allocation.AllocationError("a recommendation needs who asked for it")
    now = require_utc(now)
    limits = limits or allocation.Limits()
    result = allocation.recommend(
        returns, health, method=method, limits=limits, target_vol=target_vol
    )
    row = conn.execute(
        "INSERT INTO allocation_recommendation (method, limits, target_vol, health, inputs_sha256, weights, cash, notes, risk_contribution, created_by, created_at)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING recommendation_id",
        (
            method,
            Jsonb({"max_single": limits.max_single, "max_total": limits.max_total}),
            target_vol,
            Jsonb(dict(health)),
            inputs_hash(returns, health),
            Jsonb(result.weights),
            min(max(result.cash, 0.0), 1.0),
            Jsonb(result.notes),
            Jsonb(result.risk_contribution),
            by.strip(),
            now,
        ),
    ).fetchone()
    assert row is not None
    return int(row[0]), result


def changes_since_last(
    conn: psycopg.Connection, recommendation_id: int
) -> dict[str, tuple[float, float]]:
    """{strategy: (previous weight, new weight)} for every strategy whose weight differs from the recommendation before this one; empty if there is none."""
    rows = conn.execute(
        "SELECT recommendation_id, weights FROM allocation_recommendation WHERE recommendation_id <= %s ORDER BY recommendation_id DESC LIMIT 2",
        (recommendation_id,),
    ).fetchall()
    if len(rows) < 2 or rows[0][0] != recommendation_id:
        return {}
    new, old = rows[0][1], rows[1][1]
    return {
        k: (old.get(k, 0.0), new.get(k, 0.0))
        for k in sorted(set(new) | set(old))
        if abs(old.get(k, 0.0) - new.get(k, 0.0)) > 1e-12
    }
