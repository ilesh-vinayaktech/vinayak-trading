# ruff: noqa: E501
"""Load the point-in-time swing scores a screener strategy reads, once per run (the strategy itself holds no database). Nothing dated after `until` is kept, so a study's
research run never even holds the holdout period's scores."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta

import psycopg

from algo.strategies.scorebook import MAX_AGE_DAYS, ScoreBook

COLUMNS = {
    "score": "score",
    "score_trend": "trend",
    "score_participation": "participation",
    "score_smart_money": "smart_money",
    "score_quality": "quality",
}  # field -> column


def load(conn: psycopg.Connection, ids: Sequence[int], since: date, until: date) -> ScoreBook:
    """Rows from MAX_AGE_DAYS before `since` (the first decision day may use the previous weekly row) up to `until`."""
    rows: dict[int, list[tuple[date, dict[str, float]]]] = defaultdict(list)
    cols = ", ".join(COLUMNS.values())
    for iid, day, *vals in conn.execute(
        f"SELECT instrument_id, day, {cols} FROM stock_score_history WHERE instrument_id = ANY(%s) AND day >= %s AND day <= %s ORDER BY instrument_id, day",
        (list(ids), since - timedelta(days=MAX_AGE_DAYS), until),
    ):
        rows[iid].append(
            (day, {f: float(v) for f, v in zip(COLUMNS, vals, strict=True) if v is not None})
        )
    return ScoreBook(dict(rows))
