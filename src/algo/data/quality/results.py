# ruff: noqa: E501
"""Stored results of the data-quality checks (`dq_result`, migration 075). A check that finds nothing records one PASS row; every finding is its own FAIL
row with its subject. Append-only: history of what was found when."""

from __future__ import annotations

from datetime import date, datetime

import psycopg

from algo.core.clock import require_utc
from algo.data.quality.completeness import Report


def _add(
    conn: psycopg.Connection,
    now: datetime,
    check: str,
    scope: str,
    subject: str | None,
    status: str,
    detail: str,
) -> None:
    conn.execute(
        "INSERT INTO dq_result (run_at, check_name, scope, subject, status, detail) VALUES (%s,%s,%s,%s,%s,%s)",
        (now, check, scope, subject, status, detail),
    )


def record_completeness(
    conn: psycopg.Connection, report: Report, since: date, now: datetime
) -> int:
    """Store a completeness report; returns how many rows were written."""
    now, scope = require_utc(now), f"nse bar_1d since {since}"
    n = 0
    for d in report.quarantined:
        _add(
            conn,
            now,
            "completeness.quarantined",
            scope,
            str(d),
            "FAIL",
            "the NSE file was refused and not recovered",
        )
        n += 1
    for d in report.missing_days:
        _add(
            conn,
            now,
            "completeness.missing_day",
            scope,
            str(d),
            "FAIL",
            "an open weekday with no bars that is not a recorded holiday",
        )
        n += 1
    for d, bars, avg in report.thin_days:
        _add(
            conn,
            now,
            "completeness.thin_day",
            scope,
            str(d),
            "FAIL",
            f"{bars} bars against about {avg}",
        )
        n += 1
    if n == 0:
        _add(conn, now, "completeness", scope, None, "PASS", "no quarantined, missing or thin day")
        n = 1
    return n


def latest(conn: psycopg.Connection, check_prefix: str) -> tuple[str, datetime] | None:
    """(status of the newest run, when) for a check: FAIL if any finding of that newest run failed; None if it never ran."""
    row = conn.execute(
        "SELECT max(run_at) FROM dq_result WHERE check_name = %s OR check_name LIKE %s",
        (check_prefix, check_prefix + ".%"),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    failed = conn.execute(
        "SELECT 1 FROM dq_result WHERE run_at=%s AND status='FAIL' AND (check_name = %s OR check_name LIKE %s) LIMIT 1",
        (row[0], check_prefix, check_prefix + ".%"),
    ).fetchone()
    return ("FAIL" if failed else "PASS", row[0])
