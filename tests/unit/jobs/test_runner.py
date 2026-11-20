import subprocess
from datetime import UTC, datetime

from algo.core.clock import SimClock
from algo.jobs.runner import EX_SKIP, Job, run_job

CLOCK = SimClock(datetime(2026, 11, 13, 13, 0, tzinfo=UTC))  # 18:30 IST


def go(job, codes, tmp_path, token=False, **kw):
    alerts, calls, sleeps = [], [], []
    it = iter(codes)

    def run(argv, **k):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, next(it))

    if token:
        kw.setdefault("session_ok", lambda _now: True)
    rc = run_job(job, clock=CLOCK, alert=alerts.append, lock_dir=tmp_path / "l", log_dir=tmp_path / "g",
                 env={"ALGO_DB_URL": "pg://x"}, run=run, sleep=sleeps.append, **kw)  # fmt: skip
    return rc, alerts, calls, sleeps


def test_ok_fills_dates_and_db_and_stops_at_first_failing_step(tmp_path):
    job = Job("j", "x", (("a.py", "{db}", "{today}", "{d7}", "{d30}"), ("b.py",)), "d")
    rc, alerts, calls, _ = go(job, [0, 0], tmp_path)
    assert (rc, alerts) == (0, [])
    assert calls[0] == ["a.py", "pg://x", "2026-11-13", "2026-11-06", "2026-10-14"]
    rc, alerts, calls, _ = go(job, [3], tmp_path)
    assert rc == 1 and len(calls) == 1 and "a.py exited 3" in alerts[0]
    log = (tmp_path / "g/j_20261113.log").read_text()
    assert "{db}" in log and "pg://x" not in log  # the password never reaches the log


def windows(tmp_path, last):
    job = Job("j", "x", (("a.py", "{today}", "{d1}", "{d7}", "{d30}", "{d120}"),), "d")
    _, _, calls, _ = go(job, [0], tmp_path, last_success=lambda name: last if name == "j" else None)
    return calls[0][1:]


def test_a_window_reaches_back_to_the_last_success_when_runs_were_missed(tmp_path):
    normal = ["2026-11-13", "2026-11-12", "2026-11-06", "2026-10-14", "2026-07-16"]
    assert windows(tmp_path, None) == normal  # never succeeded: the plain windows
    assert windows(tmp_path, datetime(2026, 11, 12, 13, 0, tzinfo=UTC)) == [  # yesterday: only d1 moves, one day back (an overlap)
        "2026-11-13", "2026-11-11", "2026-11-06", "2026-10-14", "2026-07-16",
    ]  # fmt: skip
    assert windows(tmp_path, datetime(2026, 11, 9, 13, 0, tzinfo=UTC)) == [  # 4 days ago: d1 stretches to the day before
        "2026-11-13", "2026-11-08", "2026-11-06", "2026-10-14", "2026-07-16",
    ]  # fmt: skip
    assert windows(tmp_path, datetime(2026, 10, 20, 13, 0, tzinfo=UTC)) == [  # 24 days ago: d1 and d7 stretch, d30 and d120 already cover it
        "2026-11-13", "2026-10-19", "2026-10-19", "2026-10-14", "2026-07-16",
    ]  # fmt: skip


def test_the_last_success_day_is_the_indian_day_of_its_start(tmp_path):
    # 20:00 UTC on 8 Nov is 01:30 IST on 9 Nov: the window starts the day before THAT day
    got = windows(tmp_path, datetime(2026, 11, 8, 20, 0, tzinfo=UTC))
    assert got[1] == "2026-11-08"


def test_a_very_old_success_is_capped_not_unbounded(tmp_path):
    got = windows(tmp_path, datetime(2024, 1, 1, tzinfo=UTC))
    assert got[1:] == ["2025-10-09"] * 4  # 400 days before 2026-11-13


def test_retries_then_succeeds_without_alert(tmp_path):
    job = Job("j", "x", (("a",), ("check.py",)), "d", retries=2, retry_wait_s=7)
    rc, alerts, calls, sleeps = go(job, [0, 1, 0, 0], tmp_path)
    assert (rc, alerts, sleeps, len(calls)) == (0, [], [7], 4)


def test_retries_exhausted_alerts_once(tmp_path):
    job = Job("j", "x", (("a.py",),), "d", retries=1)
    rc, alerts, _, sleeps = go(job, [1, 1], tmp_path)
    assert rc == 1 and len(alerts) == 1 and "2 attempt" in alerts[0] and len(sleeps) == 1


def test_timeout_is_a_failure(tmp_path):
    job = Job("j", "x", (("a.py",),), "d")
    alerts = []

    def run(argv, **k):
        raise subprocess.TimeoutExpired(argv, 1)

    rc = run_job(
        job, clock=CLOCK, alert=alerts.append, lock_dir=tmp_path, log_dir=tmp_path, env={}, run=run
    )
    assert rc == 1 and "exited 124" in alerts[0]


def test_step_exit_75_is_skipped_not_retried(tmp_path):
    job = Job("j", "x", (("a.py",),), "d", retries=3)
    rc, alerts, calls, _ = go(job, [EX_SKIP], tmp_path)
    assert rc == EX_SKIP and len(calls) == 1 and "SKIPPED" in alerts[0]


def test_needs_kite_skips_without_session_and_runs_with_one(tmp_path):
    job = Job("j", "x", (("a.py",),), "d", needs_kite=True)
    rc, alerts, calls, _ = go(job, [], tmp_path)
    assert rc == EX_SKIP and calls == [] and "Kite" in alerts[0]
    rc, alerts, calls, _ = go(job, [0], tmp_path, token=True)
    assert (rc, alerts, len(calls)) == (0, [], 1)


def test_second_run_while_locked_does_nothing(tmp_path):
    import fcntl

    (tmp_path / "l").mkdir()
    with (tmp_path / "l/j.lock").open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        rc, alerts, calls, _ = go(Job("j", "x", (("a.py",),), "d"), [], tmp_path)
    assert (rc, alerts, calls) == (0, [], [])


def test_telegram_alert_falls_back_to_stdout_and_survives_send_failure(capsys, monkeypatch):
    from algo.jobs import runner

    runner.telegram_alert({})("hi")
    assert "ALERT: hi" in capsys.readouterr().out

    def boom(*a, **k):
        raise OSError("down")

    monkeypatch.setattr(runner.urllib.request, "urlopen", boom)
    runner.telegram_alert({"ALGO_TELEGRAM_TOKEN": "t", "ALGO_TELEGRAM_CHAT": "c"})("hi")
    assert "telegram failed" in capsys.readouterr().out


def test_telegram_alert_posts_json(monkeypatch):
    from algo.jobs import runner

    seen = []

    class R:
        def read(self):
            return b""

    monkeypatch.setattr(
        runner.urllib.request, "urlopen", lambda req, timeout: seen.append(req) or R()
    )
    runner.telegram_alert({"ALGO_TELEGRAM_TOKEN": "t", "ALGO_TELEGRAM_CHAT": "c"})("hi")
    assert seen[0].full_url.endswith("/bott/sendMessage") and b'"chat_id": "c"' in seen[0].data


# --- every run is reported, so the portal can show when each job last ran and how it went ---
def test_an_ok_run_is_recorded_with_its_times_and_attempts(tmp_path):
    runs = []
    job = Job("j", "x", (("a",), ("check.py",)), "d", retries=2)
    go(job, [0, 1, 0, 0], tmp_path, record=runs.append)
    (r,) = runs
    assert (r.job, r.status, r.attempts, r.detail) == ("j", "ok", 2, "")
    assert r.started_at == CLOCK.now() and r.finished_at >= r.started_at


def test_a_failed_run_records_which_step_failed(tmp_path):
    runs = []
    go(Job("j", "x", (("a.py",),), "d", retries=1), [1, 1], tmp_path, record=runs.append)
    assert [(r.status, r.attempts, r.detail) for r in runs] == [("failed", 2, "a.py exited 1")]


def test_a_skipped_run_records_why(tmp_path):
    runs = []
    go(Job("j", "x", (("a.py",),), "d", needs_kite=True), [], tmp_path, record=runs.append)
    assert [(r.status, r.attempts) for r in runs] == [("skipped", 0)]
    assert "no valid Kite session" in runs[0].detail
    runs.clear()
    go(Job("k", "x", (("a.py",),), "d"), [EX_SKIP], tmp_path, record=runs.append)
    assert [(r.status, r.attempts) for r in runs] == [("skipped", 1)]


def test_a_recorder_that_breaks_never_hides_the_job_result(tmp_path):
    def broken(_run):
        raise OSError("database is down")

    rc, alerts, _, _ = go(Job("j", "x", (("a.py",),), "d"), [0], tmp_path, record=broken)
    assert (rc, alerts) == (0, [])


# --- the Kite session is the portal's data feed in the database, never a file ---
def test_a_kite_job_runs_when_the_portal_feed_is_valid_(tmp_path):
    runs = []
    job = Job("k", "x", (("a.py",),), "d", needs_kite=True)
    rc, alerts, calls, _ = go(job, [0], tmp_path, record=runs.append, session_ok=lambda _now: True)
    assert (rc, alerts, len(calls)) == (0, [], 1) and runs[0].status == "ok"


def test_a_kite_job_is_skipped_when_the_feed_has_no_session(tmp_path):
    job = Job("k", "x", (("a.py",),), "d", needs_kite=True)
    rc, alerts, calls, _ = go(job, [], tmp_path, session_ok=lambda _now: False)
    assert (rc, len(calls)) == (EX_SKIP, 0) and "no valid Kite session" in alerts[0]


def test_a_feed_check_that_breaks_counts_as_no_session_not_as_a_crash(tmp_path):
    def broken(_now):
        raise OSError("database is down")

    job = Job("k", "x", (("a.py",),), "d", needs_kite=True)
    rc, alerts, _, _ = go(job, [], tmp_path, session_ok=broken)
    assert rc == EX_SKIP and "no valid Kite session" in alerts[0]
