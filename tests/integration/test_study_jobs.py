"""The study queue: two kinds of job per study (trials, verdict), one active at a time, and what each reads back."""

from datetime import UTC, date, datetime

import pytest

from algo.backtest.validation import registry
from algo.backtest.validation.gates import Evidence, Thresholds, evaluate
from algo.core.clock import SimClock
from algo.data.store.migrate import migrate
from algo.research import study_jobs
from tests.support.portal import add_user

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)


@pytest.fixture
def env(conn):
    migrate(conn)
    owner = add_user(conn, SimClock(NOW), "TRADER", "jane@example.com")
    study = {"combinations": [{"a": 1}, {"a": 2}]}
    exp = registry.register(conn, name="S", strategy_id="s", hypothesis="h", style="long_only",
                            param_ranges={"a": [1, 2]}, holdout=(date(2026, 1, 1), date(2026, 2, 1)),
                            now=NOW, study=study)  # fmt: skip
    return conn, owner, exp


def test_the_two_kinds_of_job_are_kept_apart_but_share_one_active_slot(env):
    conn, owner, exp = env
    trials = study_jobs.enqueue(conn, exp, owner, NOW)
    with pytest.raises(study_jobs.JobError, match="already"):
        study_jobs.enqueue(
            conn, exp, owner, NOW, kind="verdict"
        )  # one at a time, whatever the kind
    study_jobs.finish(conn, trials, "DONE", NOW)
    verdict = study_jobs.enqueue(conn, exp, owner, NOW, kind="verdict")
    assert study_jobs.get_run(conn, verdict)["kind"] == "verdict"
    assert study_jobs.latest_run(conn, exp)["run_id"] == trials  # the trials panel's job
    assert study_jobs.latest_run(conn, exp, "verdict")["run_id"] == verdict


def test_an_unknown_study_cannot_be_queued_or_counted(env):
    conn, owner, _ = env
    with pytest.raises(study_jobs.JobError, match="no such study"):
        study_jobs.enqueue(conn, 9999, owner, NOW)
    with pytest.raises(study_jobs.JobError, match="no such study"):
        study_jobs.trials_finished(conn, 9999)


def test_finished_trials_are_counted_against_the_planned_combinations(env):
    conn, _, exp = env
    assert study_jobs.trials_finished(conn, exp) == (0, 2)
    study_jobs.save_trial(conn, exp, {"a": 1}, "h1", "DONE", NOW, returns=[0.01])
    study_jobs.save_trial(conn, exp, {"a": 2}, "h2", "FAILED", NOW, error="x")
    assert study_jobs.trials_finished(conn, exp) == (1, 2)  # a failed one is not finished
    assert study_jobs.done_hashes(conn, exp) == {"h1"} and study_jobs.trial_returns(conn, exp) == {
        "h1": [0.01]
    }


def test_the_latest_verdict_report_is_the_newest_one(env):
    conn, _, exp = env
    assert study_jobs.latest_report(conn, exp) is None
    run_id = conn.execute(
        "INSERT INTO backtest_run (strategy_id,strategy_version,params,params_hash,code_version,reader_mode,config,"
        "cost_model,adjustment_versions,provisional_events,unapplied_events,blocked_instruments,unmodelled_events,"
        "accounting_complete,dividends_received,metrics,result_hash,created_at,ledger_reconciled,reconciliation,pnl)"
        " VALUES ('s','1','{}','ph','c','research','{}','{}','{}','[]','[]','[]','[]',true,0,'{}','rh',%s,true,'{}','{}')"
        " RETURNING run_id", (NOW,)).fetchone()[0]  # fmt: skip
    ev = Evidence()
    for n in (1, 2):
        registry.save_report(
            conn, exp, run_id, evaluate(ev, Thresholds(*([0.0] * 12)), "confirmed"), ev, n, NOW
        )
    got = study_jobs.latest_report(conn, exp)
    assert got["n_trials"] == 2 and got["passed"] is False and len(got["gates"]) == 14
