"""The study queue: two kinds of job per study (trials, verdict), one active at a time, and what each reads back."""

from datetime import UTC, date, datetime

import psycopg
import pytest

from algo.backtest.validation import registry
from algo.backtest.validation.gates import Evidence, Thresholds, evaluate
from algo.core.clock import SimClock
from algo.data.store.migrate import migrate
from algo.research import study_jobs
from tests.support.portal import add_user
from tests.support.research_lock import anchor_open_lock

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)


@pytest.fixture
def env(conn):
    migrate(conn)
    anchor_open_lock(conn)
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


# --- several workers at once: each takes its own run, and a restart only recovers runs nobody is working on ---
def _second_study(conn, owner):
    return registry.register(conn, name="S2", strategy_id="s", hypothesis="h", style="long_only",
                             param_ranges={"a": [1, 2]}, holdout=(date(2026, 1, 1), date(2026, 2, 1)),
                             now=NOW, study={"combinations": [{"a": 1}, {"a": 2}]})  # fmt: skip


def test_two_workers_take_different_runs(env, pg_url):
    conn, owner, exp = env
    first = study_jobs.enqueue(conn, exp, owner, NOW)
    second = study_jobs.enqueue(conn, _second_study(conn, owner), owner, NOW)
    with psycopg.connect(pg_url, autocommit=True) as other:
        assert study_jobs.claim(conn, NOW) == first
        assert study_jobs.claim(other, NOW) == second  # not the one the first worker holds
        assert study_jobs.claim(other, NOW) is None


def test_a_starting_worker_leaves_alone_a_run_another_live_worker_is_running(env, pg_url):
    conn, owner, exp = env
    run = study_jobs.enqueue(conn, exp, owner, NOW)
    with psycopg.connect(pg_url, autocommit=True) as busy:
        assert study_jobs.claim(busy, NOW) == run
        assert study_jobs.requeue_orphans(conn) == 0  # a new worker starts: it is not its to take
        assert study_jobs.get_run(conn, run)["status"] == "RUNNING"


def test_a_run_whose_worker_died_is_put_back_in_the_queue(env, pg_url):
    conn, owner, exp = env
    run = study_jobs.enqueue(conn, exp, owner, NOW)
    with psycopg.connect(pg_url, autocommit=True) as dying:
        assert study_jobs.claim(dying, NOW) == run
    assert study_jobs.requeue_orphans(conn) == 1  # its connection is gone, so is its claim
    assert study_jobs.get_run(conn, run)["status"] == "QUEUED"
    assert study_jobs.claim(conn, NOW) == run


def test_a_finished_run_is_released_so_nothing_holds_it(env, pg_url):
    conn, owner, exp = env
    run = study_jobs.enqueue(conn, exp, owner, NOW)
    with psycopg.connect(pg_url, autocommit=True) as worker:
        study_jobs.claim(worker, NOW)
        study_jobs.release(worker, run)
        assert study_jobs.requeue_orphans(conn) == 1  # still marked RUNNING, but nobody holds it


# --- a run asked to carry on queues the next stage by itself ---
def _report(conn, exp, passed):
    run_id = conn.execute(
        "INSERT INTO backtest_run (strategy_id,strategy_version,params,params_hash,code_version,reader_mode,config,"
        "cost_model,adjustment_versions,provisional_events,unapplied_events,blocked_instruments,unmodelled_events,"
        "accounting_complete,dividends_received,metrics,result_hash,created_at,ledger_reconciled,reconciliation,pnl)"
        " VALUES ('s','1','{}','ph','c','research','{}','{}','{}','[]','[]','[]','[]',true,0,'{}','rh',%s,true,'{}','{}')"
        " RETURNING run_id", (NOW,)).fetchone()[0]  # fmt: skip
    conn.execute(
        "INSERT INTO validation_report (experiment_id, run_id, passed, thresholds_status, n_trials, evidence, gates, created_at)"
        " VALUES (%s,%s,%s,'confirmed',1,'{}','[]',%s)",
        (exp, run_id, passed, NOW),
    )


def _queued(conn, exp):
    return conn.execute(
        "SELECT kind, chain, requested_by FROM study_run WHERE experiment_id=%s AND status='QUEUED'",
        (exp,),
    ).fetchone()


def test_a_chained_run_queues_the_verdict_and_then_the_inner_holdout_only_if_it_passed(env):
    conn, owner, exp = env
    plain = study_jobs.enqueue(conn, exp, owner, NOW)
    study_jobs.finish(conn, plain, "DONE", NOW)
    assert (
        study_jobs.chain_next(conn, plain, NOW) is None and _queued(conn, exp) is None
    )  # not asked to carry on
    trials = study_jobs.enqueue(
        conn, exp, owner, NOW, chain=True
    )  # (an older DONE trials run is superseded by the newer one)
    study_jobs.finish(conn, trials, "DONE", NOW)
    assert study_jobs.chain_next(conn, trials, NOW) == "verdict"
    assert _queued(conn, exp) == (
        "verdict",
        True,
        owner,
    )  # asked by the same person, and still carrying on
    assert study_jobs.chain_next(conn, trials, NOW) is None  # already queued: nothing twice
    verdict = study_jobs.latest_run(conn, exp, "verdict")["run_id"]
    _report(conn, exp, True)
    study_jobs.finish(conn, verdict, "DONE", NOW)
    assert (
        study_jobs.chain_next(conn, verdict, NOW) == "holdout"
        and _queued(conn, exp)[0] == "holdout"
    )
    holdout = study_jobs.latest_run(conn, exp, "holdout")["run_id"]
    study_jobs.finish(conn, holdout, "DONE", NOW)
    assert study_jobs.chain_next(conn, holdout, NOW) is None  # the end of the pipeline


def test_a_chain_stops_at_a_failed_verdict_a_failed_run_or_a_missing_run(env):
    conn, owner, exp = env
    trials = study_jobs.enqueue(conn, exp, owner, NOW, chain=True)
    study_jobs.finish(conn, trials, "FAILED", NOW)
    assert study_jobs.chain_next(conn, trials, NOW) is None  # it did not end DONE
    verdict = study_jobs.enqueue(conn, exp, owner, NOW, kind="verdict", chain=True)
    _report(conn, exp, False)
    study_jobs.finish(conn, verdict, "DONE", NOW)
    assert (
        study_jobs.chain_next(conn, verdict, NOW) is None and _queued(conn, exp) is None
    )  # failed development: no holdout
    assert study_jobs.chain_next(conn, 99999, NOW) is None  # no such run
