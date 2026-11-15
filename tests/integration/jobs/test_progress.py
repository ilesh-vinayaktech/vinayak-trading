# ruff: noqa: E501
from datetime import UTC, datetime, timedelta

import pytest

from algo.core.clock import SimClock
from algo.data.store.migrate import migrate
from algo.jobs import progress

pytestmark = pytest.mark.integration
T0 = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)


def row(conn, run_id):
    return conn.execute(
        "SELECT status, done, total, phase, message, started_at, updated_at, finished_at FROM job_progress WHERE run_id=%s",
        (run_id,),
    ).fetchone()


def test_a_run_shows_where_it_is_and_finishes_done_with_every_step_counted(conn):
    migrate(conn)
    clock = SimClock(T0)
    p = progress.Progress(conn, clock, "feature_validation", "Feature validation", 12, pid=4242)
    rid = p.start()
    assert row(conn, rid)[:5] == ("RUNNING", 0, 12, "starting", "") and row(conn, rid)[7] is None
    clock.advance(timedelta(seconds=90))
    p.step("reading prices", "first of two reads")
    assert row(conn, rid)[:5] == ("RUNNING", 0, 12, "reading prices", "first of two reads") and row(
        conn, rid
    )[6] == T0 + timedelta(seconds=90)
    p.step("checking ret_5d", "look-ahead cut 2 of 5", done=3)
    assert row(conn, rid)[1] == 3
    p.step("checking ret_20d")  # no `done` given: the count stays where it was
    assert row(conn, rid)[1] == 3
    clock.advance(timedelta(minutes=10))
    p.finish(True, "12 checked")
    status, done, total, phase, message, started, updated, finished = row(conn, rid)
    assert (
        (status, done, total, phase, message) == ("DONE", 12, 12, "finished", "12 checked")
        and started == T0
        and finished == updated == T0 + timedelta(seconds=90) + timedelta(minutes=10)
    )


def test_the_context_manager_always_finishes_the_run_and_records_the_error_when_it_fails(conn):
    migrate(conn)
    clock = SimClock(T0)
    with progress.Progress(conn, clock, "j", "A job", 2) as ok:
        ok.step("working", done=1)
    assert row(conn, ok.run_id)[:4] == ("DONE", 2, 2, "finished")
    with (
        pytest.raises(RuntimeError, match="boom"),
        progress.Progress(conn, clock, "j", "A job", 2) as bad,
    ):
        bad.step("working", done=1)
        raise RuntimeError("boom")
    status, done, _, phase, message, *_ = row(conn, bad.run_id)
    assert (status, done, phase, message) == (
        "FAILED",
        1,
        "failed",
        "RuntimeError: boom",
    )  # a failed run keeps how far it got


def test_a_finished_run_is_never_changed_again_and_bad_calls_are_refused(conn):
    migrate(conn)
    p = progress.Progress(conn, SimClock(T0), "j", "A job", 3)
    with pytest.raises(RuntimeError, match="not started"):
        p.step("x")
    with pytest.raises(RuntimeError, match="not started"):
        p.finish(True)
    p.start()
    with pytest.raises(ValueError, match="outside 0..3"):
        p.step("x", done=4)
    with pytest.raises(ValueError, match="outside 0..3"):
        p.step("x", done=-1)
    p.finish(False, "x" * 900)
    assert len(row(conn, p.run_id)[4]) == 500  # a message is cut, never refused
    p.step("late")  # a late update after the end is ignored
    p.finish(True)
    assert row(conn, p.run_id)[:4] == ("FAILED", 0, 3, "failed")
    with pytest.raises(ValueError, match="at least one step"):
        progress.Progress(conn, SimClock(T0), "j", "A job", 0)


def test_a_run_whose_process_is_gone_is_marked_failed_and_a_live_one_is_left_alone(conn):
    migrate(conn)
    clock = SimClock(T0)
    gone = progress.Progress(conn, clock, "j", "Gone", 2, pid=111)
    live = progress.Progress(conn, clock, "j", "Live", 2, pid=222)
    done = progress.Progress(conn, clock, "j", "Done", 2, pid=333)
    for p in (gone, live, done):
        p.start()
    done.finish(True)
    clock.advance(timedelta(minutes=5))
    assert progress.reap(conn, clock, is_alive=lambda pid: pid != 111) == 1
    assert (
        row(conn, gone.run_id)[0] == "FAILED"
        and row(conn, gone.run_id)[4] == "the process ended without finishing"
        and row(conn, gone.run_id)[7] == T0 + timedelta(minutes=5)
    )
    assert row(conn, live.run_id)[0] == "RUNNING" and row(conn, done.run_id)[0] == "DONE"
    assert progress.reap(conn, clock, is_alive=lambda pid: False) == 1  # only the one still RUNNING


def test_alive_tells_a_real_process_from_a_missing_one():
    import os

    assert progress.alive(os.getpid())
    assert not progress.alive(2**22 + 12345)  # above the usual pid limit


def test_recent_lists_running_jobs_first_then_the_newest_and_old_finished_runs_are_cleared(conn):
    migrate(conn)
    clock = SimClock(T0)
    old = progress.Progress(conn, clock, "old", "Old", 1)
    old.start()
    old.finish(True)
    clock.advance(timedelta(days=progress.KEEP_DAYS + 1))
    older_running = progress.Progress(conn, clock, "long", "Long", 5)
    older_running.start()
    clock.advance(timedelta(hours=1))
    newer = progress.Progress(conn, clock, "new", "New", 1)
    newer.start()  # clears the finished run older than the keep window
    newer.finish(True)
    out = progress.recent(conn)
    assert [r["job"] for r in out] == [
        "long",
        "new",
    ]  # RUNNING first; the 31-day-old finished run is gone
    assert out[0]["status"] == "RUNNING" and out[0]["total"] == 5 and out[1]["status"] == "DONE"
    assert len(progress.recent(conn, limit=1)) == 1


def test_a_process_owned_by_someone_else_still_counts_as_alive(monkeypatch):
    def deny(pid, sig):
        raise PermissionError

    monkeypatch.setattr(progress.os, "kill", deny)
    assert progress.alive(1)


def test_a_job_that_only_learns_its_step_count_after_starting_can_set_the_total(conn):
    migrate(conn)
    p = progress.Progress(conn, SimClock(T0), "j", "A job", 1)
    p.start()
    p.step("planning", total=24, done=0)
    assert row(conn, p.run_id)[1:3] == (0, 24)
    p.step("working", done=24)  # the new total is what counts
    assert row(conn, p.run_id)[1:3] == (24, 24)
    with pytest.raises(ValueError, match="at least one step"):
        p.step("x", total=0)
    with pytest.raises(ValueError, match="outside 0..24"):
        p.step("x", done=25)


def test_the_times_of_the_first_and_latest_finished_step_are_kept_for_estimating(conn):
    migrate(conn)
    clock = SimClock(T0)
    p = progress.Progress(conn, clock, "j", "A job", 5)
    p.start()

    def times():
        return conn.execute(
            "SELECT first_done_at, last_done_at FROM job_progress WHERE run_id=%s", (p.run_id,)
        ).fetchone()

    assert times() == (None, None)
    clock.advance(timedelta(minutes=3))
    p.step("working", "no count given")  # a message alone finishes no step
    p.step("working", done=0)
    assert times() == (None, None)
    p.step("working", done=1)
    assert times() == (T0 + timedelta(minutes=3),) * 2
    clock.advance(timedelta(minutes=2))
    p.step("working", "same count again", done=1)  # not a new step
    assert times() == (T0 + timedelta(minutes=3),) * 2
    p.step("working", done=2)
    assert times() == (T0 + timedelta(minutes=3), T0 + timedelta(minutes=5))
    clock.advance(timedelta(minutes=4))
    p.step("working", done=4)  # two steps at once still count as new work
    assert times() == (T0 + timedelta(minutes=3), T0 + timedelta(minutes=9))


def test_a_job_whose_steps_differ_a_lot_says_so(conn):
    migrate(conn)
    even = progress.Progress(conn, SimClock(T0), "j", "Even", 2)
    uneven = progress.Progress(conn, SimClock(T0), "j", "Uneven", 2, uniform=False)
    even.start()
    uneven.start()
    got = dict(conn.execute("SELECT label, uniform FROM job_progress").fetchall())
    assert got == {"Even": True, "Uneven": False}
