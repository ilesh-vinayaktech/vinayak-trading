from datetime import UTC, datetime, timedelta

import pytest

from algo.data.store.migrate import migrate
from algo.live import heartbeat
from algo.live.heartbeat import DEFAULT_EXPECTED, Expectation

pytestmark = pytest.mark.integration
OPEN = datetime(2026, 11, 16, 4, 0, tzinfo=UTC)  # Monday 09:30 IST, inside the session
CLOSED = datetime(2026, 11, 16, 11, 0, tzinfo=UTC)  # 16:30 IST, after it
SUNDAY = datetime(2026, 11, 15, 5, 0, tzinfo=UTC)


def test_a_beat_creates_then_replaces_the_row_and_keeps_when_the_process_started(conn):
    migrate(conn)
    heartbeat.beat(conn, "study_worker", "STARTING", "booting", OPEN, pid=11, host="h")
    heartbeat.beat(
        conn, "study_worker", "RUNNING", "idle", OPEN + timedelta(seconds=30), pid=11, host="h"
    )
    row = conn.execute(
        "SELECT state, detail, started_at, beat_at, pid FROM process_heartbeat"
    ).fetchone()
    assert row == ("RUNNING", "idle", OPEN, OPEN + timedelta(seconds=30), 11)
    heartbeat.beat(
        conn, "study_worker", "STARTING", "restarted", OPEN + timedelta(minutes=5), pid=22, host="h"
    )  # a restart
    assert conn.execute("SELECT started_at, pid FROM process_heartbeat").fetchone() == (
        OPEN + timedelta(minutes=5),
        22,
    )
    assert heartbeat.load(conn)["study_worker"].state == "STARTING"


def test_the_feed_is_read_from_its_own_status_row(conn):
    migrate(conn)
    assert "feed" not in heartbeat.load(conn)
    conn.execute(
        "INSERT INTO feed_status (feed_id, state, detail, subscribed, ticks_total, bars_total, bad_frames, late_ticks, updated_at)"
        " VALUES (1, 'CONNECTED', 'ok', 2596, 0, 0, 0, 0, %s)",
        (OPEN,),
    )
    assert heartbeat.load(conn)["feed"].state == "RUNNING"
    feed = [DEFAULT_EXPECTED["feed"]]
    assert heartbeat.check(conn, OPEN + timedelta(seconds=60), feed) == []
    (problem,) = heartbeat.check(
        conn, OPEN + timedelta(seconds=400), feed
    )  # the feed stopped writing: a missed heartbeat
    assert "feed has been silent for 400 s" in problem


def test_the_session_comes_from_the_market_calendar_so_the_feed_is_only_expected_then(conn):
    migrate(conn)
    feed = [DEFAULT_EXPECTED["feed"]]
    assert heartbeat.in_session(conn, OPEN) is True
    assert (
        heartbeat.in_session(conn, CLOSED) is False and heartbeat.in_session(conn, SUNDAY) is False
    )
    assert heartbeat.check(conn, OPEN, feed) == [
        "feed has never reported"
    ]  # in session and nothing from the feed
    assert heartbeat.check(conn, CLOSED, feed) == [] and heartbeat.check(conn, SUNDAY, feed) == []


def test_a_process_that_must_always_run_is_checked_outside_the_session_too(conn):
    migrate(conn)
    worker = [Expectation("study_worker", timedelta(seconds=300), session_only=False)]
    assert heartbeat.check(conn, SUNDAY, worker) == ["study_worker has never reported"]
    heartbeat.beat(conn, "study_worker", "RUNNING", "idle", SUNDAY, pid=1, host="h")
    assert heartbeat.check(conn, SUNDAY + timedelta(seconds=299), worker) == []
    assert heartbeat.check(conn, SUNDAY + timedelta(seconds=301), worker) != []
