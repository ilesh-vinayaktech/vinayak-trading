from datetime import UTC, datetime, timedelta

from algo.api.platform_health import assess, max_age_days, schedule_text

NOW = datetime(2026, 11, 13, 14, 0, tzinfo=UTC)
CURRENT = {"status": "CURRENT", "sessions_behind": 0, "latest_bar_session": "2026-11-13"}


def run(status, ago, detail="", attempts=1):
    t = NOW - ago
    return {"started_at": t.isoformat(), "finished_at": t.isoformat(), "status": status,
            "attempts": attempts, "detail": detail}  # fmt: skip


def job(name, calendar="Mon..Fri *-*-* 18:30 Asia/Kolkata", last=None, ok=None):
    return {"name": name, "calendar": calendar, "description": "d", "last_run": last,
            "last_success_at": None if ok is None else (NOW - ok).isoformat()}  # fmt: skip


def verdict(freshness=CURRENT, jobs=(), quarantined=(), kite="connected"):
    return assess(
        now=NOW,
        freshness=freshness,
        jobs=list(jobs),
        quarantined=list(quarantined),
        kite_state=kite,
    )


def texts(v):
    return [r["text"] for r in v["reasons"]]


def test_everything_current_is_ok_with_no_reasons():
    good = job("a", last=run("ok", timedelta(hours=2)), ok=timedelta(hours=2))
    assert verdict(jobs=[good]) == {"status": "OK", "reasons": []}


def test_data_one_session_behind_needs_attention_two_or_none_is_down():
    one = {"status": "STALE", "sessions_behind": 1, "latest_bar_session": "2026-11-12"}
    v = verdict(freshness=one)
    assert (
        v["status"] == "ATTENTION"
        and "1 session behind" in texts(v)[0]
        and "2026-11-12" in texts(v)[0]
    )
    two = {**one, "sessions_behind": 3}
    v = verdict(freshness=two)
    assert (
        v["status"] == "DOWN"
        and v["reasons"][0]["level"] == "down"
        and "3 sessions behind" in texts(v)[0]
    )
    v = verdict(freshness=None)
    assert v["status"] == "DOWN" and texts(v) == ["No price data is loaded yet."]


def test_a_failed_last_run_is_named_with_how_long_ago_and_why():
    j = job(
        "kite-reconcile",
        last=run("failed", timedelta(hours=2), "reconcile.py exited 3", 3),
        ok=timedelta(days=1),
    )
    v = verdict(jobs=[j])
    assert v["status"] == "ATTENTION"
    assert texts(v) == ["kite-reconcile failed 2 h ago after 3 attempts: reconcile.py exited 3."]


def test_a_job_that_has_not_succeeded_for_longer_than_its_schedule_allows_is_overdue():
    weekday = job(
        "w", last=run("ok", timedelta(days=6)), ok=timedelta(days=6)
    )  # a weekday job: 5 days at most
    daily = job("d", "*-*-* 22:00 Asia/Kolkata", run("ok", timedelta(days=3)), timedelta(days=3))
    weekly = job(
        "k", "Sun *-*-* 03:00 Asia/Kolkata", run("ok", timedelta(days=8)), timedelta(days=8)
    )  # fine
    monthly = job(
        "m", "*-*-05 10:00 Asia/Kolkata", run("ok", timedelta(days=40)), timedelta(days=40)
    )
    v = verdict(jobs=[weekday, daily, weekly, monthly])
    assert texts(v) == [
        "w has not succeeded for 6 d (it runs Mon..Fri 18:30 IST).",
        "d has not succeeded for 3 d (it runs Daily 22:00 IST).",
        "m has not succeeded for 40 d (it runs Day 5 of the month, 10:00 IST).",
    ]


def test_a_skipped_job_is_not_blamed_on_its_own_the_kite_reason_covers_it():
    j = job(
        "kite-daily-candles",
        last=run("skipped", timedelta(hours=1), "no valid Kite session"),
        ok=timedelta(hours=20),
    )
    assert verdict(jobs=[j], kite="expired")["reasons"] == [
        {
            "level": "attention",
            "text": "The Kite session has expired: log in on the Kite page so the loaders and the live feed can run.",
        }
    ]


def test_jobs_that_never_ran_are_one_reason_not_one_each():
    jobs = [job(f"j{i}") for i in range(5)]
    v = verdict(jobs=jobs)
    assert texts(v) == ["5 scheduled jobs have never run: j0, j1, j2 and 2 more."]
    assert texts(verdict(jobs=jobs[:1])) == ["1 scheduled job has never run: j0."]
    assert texts(verdict(jobs=jobs[:3])) == ["3 scheduled jobs have never run: j0, j1, j2."]


def test_a_job_that_failed_and_is_overdue_is_reported_once():
    j = job("x", last=run("failed", timedelta(hours=1), "x.py exited 1"), ok=timedelta(days=9))
    assert len(verdict(jobs=[j])["reasons"]) == 1


def test_a_failed_job_that_never_succeeded_is_reported_once_as_failed():
    j = job("x", last=run("failed", timedelta(minutes=5), "", 1))
    assert texts(verdict(jobs=[j])) == ["x failed 5 min ago."]


def test_kite_quarantine_and_the_worst_level_wins():
    v = verdict(kite=None, quarantined=["2022-08-03", "2022-08-04"])
    assert v["status"] == "ATTENTION"
    assert texts(v) == [
        "2 partitions are quarantined: 2022-08-03, 2022-08-04.",
        "No Kite data feed is connected: the loaders and the live feed cannot run.",
    ]
    saved = verdict(kite="saved")
    assert "not connected" in texts(saved)[0]
    both = verdict(freshness=None, kite=None)
    assert both["status"] == "DOWN" and [r["level"] for r in both["reasons"]] == [
        "down",
        "attention",
    ]
    one = verdict(quarantined=["2022-08-03"])
    assert texts(one) == ["1 partition is quarantined: 2022-08-03."]


def test_how_long_a_job_may_go_without_succeeding():
    assert max_age_days("Mon..Fri *-*-* 18:30 Asia/Kolkata") == 5
    assert max_age_days("*-*-* 22:00 Asia/Kolkata") == 2
    assert max_age_days("Sun *-*-* 03:00 Asia/Kolkata") == 9
    assert max_age_days("*-*-01 10:00 Asia/Kolkata") == 35
    assert max_age_days("something else") == 2


def test_a_job_that_only_ever_skipped_has_nothing_to_be_overdue_from():
    j = job("kite-daily-candles", last=run("skipped", timedelta(hours=1), "no valid Kite session"))
    assert verdict(jobs=[j])["reasons"] == []


def test_a_schedule_reads_the_way_a_person_says_it():
    assert schedule_text("Mon..Fri *-*-* 18:30 Asia/Kolkata") == "Mon..Fri 18:30 IST"
    assert schedule_text("*-*-* 22:00 Asia/Kolkata") == "Daily 22:00 IST"
    assert schedule_text("*-*-05 10:00 Asia/Kolkata") == "Day 5 of the month, 10:00 IST"
    assert schedule_text("hourly") == "hourly"
