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
