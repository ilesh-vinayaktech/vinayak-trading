from algo.jobs.registry import JOBS, render_units


def test_unique_names_and_units_rendered():
    assert len({j.name for j in JOBS}) == len(JOBS)
    units = render_units("/app", "/uv")
    assert len(units) == len(JOBS) + 1
    assert "WorkingDirectory=/app" in units["algo-job@.service"]
    t = units["algo-job-bhavcopy-daily.timer"]
    assert (
        "Persistent=true" in t
        and "Unit=algo-job@bhavcopy-daily.service" in t
        and "18:30 Asia/Kolkata" in t
    )


def test_every_script_a_job_runs_exists():
    from pathlib import Path

    for j in JOBS:
        for s in j.steps:
            for a in s:
                if a.endswith(".py"):
                    assert Path(a).exists(), a


def test_a_job_can_run_on_several_schedules_and_the_news_job_does():
    t = render_units("/app", "/uv")["algo-job-news-feed.timer"]
    lines = [ln for ln in t.splitlines() if ln.startswith("OnCalendar=")]
    assert lines == [
        "OnCalendar=Mon..Fri *-*-* 09..15:00/5:00 Asia/Kolkata",
        "OnCalendar=Mon..Fri *-*-* 00..08,16..23:20 Asia/Kolkata",
        "OnCalendar=Sat,Sun *-*-* *:20 Asia/Kolkata",
    ]
    one = render_units("/app", "/uv")["algo-job-bhavcopy-daily.timer"]
    assert one.count("OnCalendar=") == 1  # a single-schedule job is unchanged


def test_every_schedule_is_valid_to_systemd():
    import shutil
    import subprocess

    import pytest

    if shutil.which("systemd-analyze") is None:
        pytest.skip("systemd-analyze is not installed")
    for j in JOBS:
        for expr in j.calendar.split(";"):
            done = subprocess.run(
                ["systemd-analyze", "calendar", expr.strip()],
                capture_output=True,
                text=True,
                check=False,
            )  # noqa: S603, S607
            assert done.returncode == 0, f"{j.name}: {expr!r}: {done.stderr.strip()[:200]}"
