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


def test_a_continuity_scan_is_stored_as_one_row_per_unexplained_jump_or_one_pass(conn):
    from algo.data.quality.continuity_scan import Finding, ScanResult

    migrate(conn)
    clean = ScanResult(scanned=500)
    assert results.record_continuity(conn, clean, SINCE, NOW) == 1
    bad = ScanResult(
        scanned=500,
        unexplained=[Finding("ABC", date(2026, 11, 13), "jump", "close fell 31%")],
        pending=[Finding("XYZ", date(2026, 11, 13), "jump", "on a pending demerger")],
    )
    assert (
        results.record_continuity(conn, bad, SINCE, NOW) == 1
    )  # only the unexplained fails; pending is reported, not failed
    got = conn.execute(
        "SELECT check_name, subject, status, detail FROM dq_result ORDER BY result_id"
    ).fetchall()
    assert got[0][:3] == ("continuity", None, "PASS") and "500 stocks" in got[0][3]
    assert got[1][:3] == ("continuity.unexplained", "ABC 2026-11-13", "FAIL") and "31%" in got[1][3]
    assert results.latest(conn, "continuity")[0] == "FAIL"


def test_a_reconciliation_alerts_only_on_breaches_that_are_new_since_the_previous_run(conn):
    migrate(conn)
    scope = "kite vs nse, 2600 stocks"
    first = {"AAA": "DIVERGES: x", "BBB": "OFFSET: y"}
    # nothing recorded before: every breach is new
    assert results.new_breaches(conn, "kite_reconcile", first) == ["AAA", "BBB"]
    results.record_reconcile(conn, first, scope, NOW)
    assert results.new_breaches(conn, "kite_reconcile", first) == []  # the same backlog is not news
    assert results.new_breaches(conn, "kite_reconcile", {**first, "CCC": "STEP: z"}) == ["CCC"]
    results.record_reconcile(
        conn, {"AAA": "DIVERGES: x"}, scope, datetime(2026, 11, 16, tzinfo=UTC)
    )  # BBB cleared
    assert results.new_breaches(conn, "kite_reconcile", first) == [
        "BBB"
    ]  # and coming back is new again
    results.record_reconcile(conn, {}, scope, datetime(2026, 11, 17, tzinfo=UTC))
    assert results.latest(conn, "kite_reconcile")[0] == "PASS"
    assert results.new_breaches(conn, "kite_reconcile", {"AAA": "DIVERGES: x"}) == ["AAA"]
