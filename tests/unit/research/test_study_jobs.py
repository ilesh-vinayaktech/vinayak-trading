from datetime import UTC, datetime, timedelta

from algo.research import study_jobs
from algo.research.study_jobs import estimate

START = datetime(2026, 11, 13, 6, 0, tzinfo=UTC)


def run(**kw):
    base = {"status": "RUNNING", "total": 12, "done": 4, "step_done": 0, "step_total": 0,
            "started_at": START, "detail": {"done_at_start": 0}}  # fmt: skip
    return {**base, **kw}


def at(minutes):
    return START + timedelta(minutes=minutes)


def test_time_left_follows_the_pace_so_far():
    e = estimate(run(), at(40))  # 4 of 12 in 40 minutes: 10 minutes each, 8 to go
    assert e["fraction"] == 4 / 12 and e["elapsed_seconds"] == 2400 and e["eta_seconds"] == 4800


def test_a_partly_done_combination_counts_towards_progress_and_pace():
    e = estimate(run(done=4, step_done=550, step_total=1100), at(45))  # 4.5 of 12 in 45 minutes
    assert abs(e["fraction"] - 4.5 / 12) < 1e-9 and e["eta_seconds"] == 4500
    assert (e["step_done"], e["step_total"]) == (550, 1100)


def test_a_resumed_run_is_paced_by_the_work_it_did_this_time_not_the_trials_it_skipped():
    e = estimate(
        run(done=10, detail={"done_at_start": 8}), at(20)
    )  # only 2 done in 20 minutes; 2 left
    assert e["eta_seconds"] == 1200 and abs(e["fraction"] - 10 / 12) < 1e-9


def test_no_estimate_until_there_is_enough_work_to_judge_the_pace():
    assert estimate(run(done=0), at(5))["eta_seconds"] is None  # nothing finished yet
    assert (
        estimate(run(done=0, step_done=1, step_total=1100), at(5))["eta_seconds"] is None
    )  # 0.1% in


def test_a_waiting_finished_or_empty_run_has_no_estimate():
    assert estimate(run(status="QUEUED"), at(1)) is None
    assert estimate(run(status="DONE"), at(1)) is None
    assert estimate(run(total=0), at(1)) is None
    assert estimate(run(started_at=None), at(1)) is None


def test_the_fraction_never_exceeds_one():
    e = estimate(run(done=12, step_done=1100, step_total=1100), at(100))
    assert e["fraction"] == 1.0 and e["eta_seconds"] == 0


def test_a_verdicts_evidence_reaches_the_page_as_numbers_only():
    """The UI reads evidence as numbers; the near-twin flag is stored as true/false, so it is served as 1/0."""
    ev = {
        "oos_sharpe": 1.2,
        "pbo_twins": True,
        "pbo": None,
        "regimes": 4.0,
        "oos_sharpe_lower": 0.3,
        "other": False,
    }
    assert study_jobs.numbers_only(ev) == {
        "oos_sharpe": 1.2,
        "pbo_twins": 1.0,
        "pbo": None,
        "regimes": 4.0,
        "oos_sharpe_lower": 0.3,
        "other": 0.0,
    }
