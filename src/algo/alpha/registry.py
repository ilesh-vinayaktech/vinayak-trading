# ruff: noqa: E501
"""The alpha hypothesis registry (plan.md section 6.4): every feature-at-a-horizon that discovery tested, with the evidence it measured and a status.

Callers: tests/integration/alpha/test_registry.py and scripts/discover_alpha.py. Schema: alpha_hypothesis (migration 078, insert-only).
User's instruction: "do as much as you can do yourself, keep taking things one by one from @TODO.md and @plan.md ... keep things finishing with test".

Rules, all of them about not fooling ourselves:
  * Failed hypotheses are kept. They are what the multiple-testing correction counts.
  * A p-value is multiplied by the number of tests EVER run (Bonferroni over the whole history, this batch included): the more we look, the more
    evidence the next candidate needs. A candidate also needs a rank IC of at least `min_abs_ic` in size, because a tiny effect can be 'significant' over
    enough days and still be worthless after costs.
  * CANDIDATE means 'worth validating', never 'works'. Validation (walk-forward, costs, the holdout batch) is a separate, later gate.
  * Nothing is edited after it is written; a retest is a new row in a new batch."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from algo.alpha import stats
from algo.alpha.discover import Evidence
from algo.core.clock import require_utc

ALPHA = 0.05
MIN_ABS_IC = 0.02
METHOD = "RANK_IC"


def tests_ever_run(conn: psycopg.Connection) -> int:
    row = conn.execute("SELECT count(*) FROM alpha_hypothesis").fetchone()
    assert row is not None
    return int(row[0])


def record(
    conn: psycopg.Connection,
    evidences: Sequence[Evidence],
    dataset_sha256: str,
    now: datetime,
    *,
    alpha: float = ALPHA,
    min_abs_ic: float = MIN_ABS_IC,
    context: dict[str, Any] | None = None,
) -> list[int]:
    """Store one discovery batch; returns the hypothesis ids in the order given."""
    if not evidences:
        raise ValueError("nothing to record")
    now = require_utc(now)
    keys = [(e.feature, e.version, e.horizon) for e in evidences]
    if len(set(keys)) != len(keys):
        raise ValueError("the same hypothesis appears more than once in one batch")
    ids: list[int] = []
    with conn.transaction():
        total = tests_ever_run(conn) + len(evidences)
        row = conn.execute("SELECT coalesce(max(batch_id), 0) + 1 FROM alpha_hypothesis").fetchone()
        assert row is not None
        batch = int(row[0])
        adjusted = stats.bonferroni(
            [1.0 if e.p_value is None else e.p_value for e in evidences], total_tests=total
        )
        for e, p_adj in zip(evidences, adjusted, strict=True):
            testable = e.mean_ic is not None and e.p_value is not None
            candidate = testable and abs(e.mean_ic or 0.0) >= min_abs_ic and p_adj < alpha
            body: dict[str, Any] = {
                "sample_days": e.days,
                "avg_names": e.avg_names,
                "mean_ic": e.mean_ic,
                "std_ic": e.std_ic,
                "icir": e.icir,
                "hit_rate": e.hit_rate,
                "t_stat": e.t_stat,
                "p_value": e.p_value,
                "p_adjusted": p_adj if testable else None,
                "tests_ever_run": total,
                "alpha": alpha,
                "min_abs_ic": min_abs_ic,
                "direction": None
                if e.mean_ic is None
                else ("POSITIVE" if e.mean_ic > 0 else "NEGATIVE"),
                "discovery_result_sha256": e.sha256,
                "context": context
                or {},  # what the caller says about the data (for example that the universe is not point-in-time)
            }
            digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
            got = conn.execute(
                "INSERT INTO alpha_hypothesis (batch_id, feature_name, feature_version, horizon_days, method, dataset_sha256, research_status, validation_status, evidence, evidence_sha256, created_at)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING hypothesis_id",
                (
                    batch,
                    e.feature,
                    e.version,
                    e.horizon,
                    METHOD,
                    dataset_sha256,
                    "CANDIDATE" if candidate else "REJECTED",
                    "PENDING" if candidate else "NOT_APPLICABLE",
                    Jsonb(body),
                    digest,
                    now,
                ),
            ).fetchone()
            assert got is not None
            ids.append(int(got[0]))
    return ids
