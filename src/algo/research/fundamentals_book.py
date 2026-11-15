# ruff: noqa: E501
"""Load the filings, splits and dividends a screener strategy needs, once per study run (the strategy itself holds no database).

Nothing filed after `until` is kept, so a study's research run never even holds the holdout's filings."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal

import psycopg

from algo.screener.snapshot import FILING_YEARS, quarters_since
from algo.strategies.fundamentals import FundamentalsBook


def load(
    conn: psycopg.Connection,
    ids: Sequence[int],
    since: date,
    until: date,
    lag: timedelta = timedelta(0),
) -> FundamentalsBook:
    """Filings from `FILING_YEARS` before `since` (ratios look back several quarters), up to `until`."""
    start = since - timedelta(days=365 * FILING_YEARS)
    quarters = {
        k: [q for q in qs if q.filed_at.date() <= until]
        for k, qs in quarters_since(conn, start, ids).items()
    }
    splits: dict[int, list[date]] = defaultdict(list)
    for iid, ex in conn.execute(
        "SELECT instrument_id, ex_date FROM corporate_action WHERE kind IN ('split','bonus') AND status='ok'"
        " AND instrument_id = ANY(%s) AND ex_date <= %s ORDER BY ex_date",
        (list(ids), until),
    ):
        splits[iid].append(ex)
    dividends: dict[int, list[tuple[date, Decimal]]] = defaultdict(list)
    for iid, ex, amount in conn.execute(
        "SELECT instrument_id, ex_date, amount FROM corporate_action WHERE kind='dividend' AND status='ok'"
        " AND amount IS NOT NULL AND instrument_id = ANY(%s) AND ex_date > %s AND ex_date <= %s ORDER BY ex_date",
        (list(ids), start, until),
    ):
        dividends[iid].append((ex, amount))
    return FundamentalsBook(quarters, dict(splits), dict(dividends), lag)
