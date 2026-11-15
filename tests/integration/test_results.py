# ruff: noqa: E501
from datetime import UTC, date, datetime

import psycopg
import pytest

from algo.data.quality import results
from algo.data.quality.completeness import Report
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 15, 16, 0, tzinfo=UTC)
SINCE = date(2026, 10, 16)


def rows(conn):
    return conn.execute(
        "SELECT check_name, scope, subject, status, detail FROM dq_result ORDER BY result_id"
    ).fetchall()


def test_a_clean_run_leaves_one_pass_row_so_ran_clean_differs_from_never_ran(conn):
    migrate(conn)
    assert results.record_completeness(conn, Report(), SINCE, NOW) == 1
    assert rows(conn) == [
        (
            "completeness",
            "nse bar_1d since 2026-10-16",
            None,
            "PASS",
            "no quarantined, missing or thin day",
        )
    ]


def test_every_finding_is_its_own_fail_row_with_the_subject(conn):
    migrate(conn)
    r = Report(
        quarantined=[date(2026, 10, 20)],
        missing_days=[date(2026, 10, 21)],
        thin_days=[(date(2026, 10, 22), 900, 1900)],
    )
    assert results.record_completeness(conn, r, SINCE, NOW) == 3
    got = rows(conn)
    assert [(g[0], g[2], g[3]) for g in got] == [
        ("completeness.quarantined", "2026-10-20", "FAIL"),
        ("completeness.missing_day", "2026-10-21", "FAIL"),
        ("completeness.thin_day", "2026-10-22", "FAIL"),
    ]
    assert "900 bars against about 1900" in got[2][4]


def test_results_are_append_only_and_a_rerun_adds_rows(conn):
    migrate(conn)
    results.record_completeness(conn, Report(), SINCE, NOW)
    results.record_completeness(conn, Report(), SINCE, NOW)
    assert len(rows(conn)) == 2
    with pytest.raises(psycopg.errors.RaiseException, match="insert-only"):
        conn.execute("UPDATE dq_result SET status='FAIL'")
    with pytest.raises(psycopg.errors.RaiseException, match="insert-only"):
        conn.execute("DELETE FROM dq_result")
    assert results.latest(conn, "completeness")[0] == "PASS"
    assert results.latest(conn, "never-ran") is None
