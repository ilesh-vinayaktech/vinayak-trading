# ruff: noqa: E501
"""Stored results of the data-quality checks (`dq_result`, migration 075). A check that finds nothing records one PASS row; every finding is its own FAIL
row with its subject. Append-only: history of what was found when."""

from __future__ import annotations

from datetime import date, datetime

import psycopg

from algo.core.clock import require_utc
from algo.data.quality.completeness import Report
from algo.data.quality.continuity_scan import ScanResult


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


def record_continuity(
    conn: psycopg.Connection, scan: ScanResult, since: date, now: datetime
) -> int:
    """Store a price-continuity scan: each unexplained jump is a FAIL row; pending ones (waiting for a person) are reported by the script, not failed."""
    now, scope = require_utc(now), f"nse bar_1d raw closes since {since}"
    for f in scan.unexplained:
        _add(
            conn,
            now,
            "continuity.unexplained",
            scope,
            f"{f.symbol} {f.day}",
            "FAIL",
            f"{f.kind}: {f.detail}",
        )
    if not scan.unexplained:
        _add(
            conn,
            now,
            "continuity",
            scope,
            None,
            "PASS",
            f"{scan.scanned} stocks scanned, no unexplained jump",
        )
    return max(len(scan.unexplained), 1)


def record_reconcile(
    conn: psycopg.Connection, breaching: dict[str, str], scope: str, now: datetime
) -> int:
    """Store a Kite-versus-bhavcopy reconciliation: one FAIL row per breaching stock (subject = symbol), or one PASS row when there is none."""
    now = require_utc(now)
    for sym, why in sorted(breaching.items()):
        _add(conn, now, "kite_reconcile.breach", scope, sym, "FAIL", why)
    if not breaching:
        _add(conn, now, "kite_reconcile", scope, None, "PASS", "no stock breaches")
    return max(len(breaching), 1)


def new_breaches(conn: psycopg.Connection, check_prefix: str, current: dict[str, str]) -> list[str]:
    """Symbols breaching now that were not breaching in the newest recorded run (all of them if there is none): an old backlog is not news every day."""
    got = latest(conn, check_prefix)
    if got is None:
        return sorted(current)
    before = {
        r[0]
        for r in conn.execute(
            "SELECT subject FROM dq_result WHERE run_at=%s AND status='FAIL' AND (check_name = %s OR check_name LIKE %s) AND subject IS NOT NULL",
            (got[1], check_prefix, check_prefix + ".%"),
        )
    }
    return sorted(s for s in current if s not in before)
