"""Running a registered study's trials through the real engine, one parameter combination at a time, on synthetic prices.
ENGINEERING_TEST_ONLY data: nothing here is a strategy result."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest

from algo.backtest.costs import schedule_store
from algo.backtest.validation import registry
from algo.core.clock import SimClock
from algo.data import freeze
from algo.data.amfi_caps import CapList, CapRow
from algo.data.market_caps import load_list
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.research import study_jobs
from algo.research.study_runner import StudyRunError, run_study
from algo.research.study_store import register_study
from tests.support.portal import add_user
from tests.unit.research.test_study import spec

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)
N = 330  # sessions of data
FIRST = date(2024, 1, 1)


def sessions():
    out, d = [], FIRST
    while len(out) < N:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


DAYS = sessions()


def sawtooth(k):
    """Rises 0.4% a day; every 30 sessions (staggered by k) it drops 3% a day for four days."""
    p, out = D(100), {}
    for i, d in enumerate(DAYS):
        out[d] = p
        p *= D("0.97") if i >= 150 and (i + k) % 30 < 4 else D("1.004")
    return out


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    ids = []
    rows = []
    for k in range(8):
        iid = repo.add_instrument(x, f"S{k}", isin=f"INE00000000{k}")
        ids.append(iid)
        rows.append(CapRow(k + 1, f"INE00000000{k}", f"S{k}", f"Co {k}", D(1000 - k)))
        for d, p in sawtooth(k).items():
            conn.execute(
                "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,adjusted_through,dataset_version,ingested_at)"
                " VALUES (%s,%s,%s,%s,%s,%s,10000000,'kite',%s,1,%s)",
                (
                    iid,
                    datetime(d.year, d.month, d.day, 3, 45, tzinfo=UTC),
                    p,
                    p,
                    p,
                    p,
                    DAYS[-1],
                    NOW,
                ),
            )
    load_list(
        conn, CapList(date(2023, 6, 30), tuple(rows)), "u", "s", NOW
    )  # all eight are large caps, in force from 2023-08-01
    freeze.take(conn, "kite", DAYS[-1], datetime(2026, 11, 12, tzinfo=UTC), "synthetic reference")
    schedule_store.import_files(conn, Path("config/cost_schedules"), now=NOW)
    owner = add_user(conn, SimClock(NOW), "TRADER", "jane@example.com")
    return conn, owner


def small_spec(**over):
    base = {
        "name": "tiny",
        "grid": {"trend_sma": [100], "entry_rsi": [25, 30], "exit_rsi": [60], "max_positions": [5]},
        "universe": {"segments": ["large"], "min_history_sessions": 110},
        "start": DAYS[0].isoformat(), "end": DAYS[-1].isoformat(), "holdout_start": DAYS[270].isoformat(),
        "accept_survivorship_bias": True, "capital": "1000000",
    }  # fmt: skip
    return spec(**{**base, **over})


def registered(conn, owner, **over):
    return register_study(conn, owner, small_spec(**over), NOW)


def test_every_combination_is_run_over_the_research_window_and_recorded_as_a_trial(env):
    conn, owner = env
    sid = registered(conn, owner)
    rid = study_jobs.enqueue(conn, sid, owner, NOW)
    run_study(conn, rid, NOW)
    trials = study_jobs.trials(conn, sid)
    assert [t["params"]["entry_rsi"] for t in trials] == [25, 30] and len(trials) == 2
    t = trials[0]
    assert t["status"] == "DONE" and t["variant"] == "base" and t["seconds"] >= 0
    assert set(t["metrics"]) >= {
        "sharpe",
        "cagr",
        "max_drawdown",
        "total_return",
        "trades",
        "costs",
        "days",
    }
    assert t["metrics"]["trades"] > 0 and t["metrics"]["days"] >= 100
    assert registry.trial_count(conn, sid) == 2  # the registry's counter feeds the deflated Sharpe
    run = study_jobs.get_run(conn, rid)
    assert (run["status"], run["done"], run["total"], run["error"]) == ("DONE", 2, 2, None)
    assert run["finished_at"] is not None


def test_the_holdout_is_never_touched_and_the_research_window_ends_the_day_before_it(env):
    conn, owner = env
    sid = registered(conn, owner)
    run_study(conn, study_jobs.enqueue(conn, sid, owner, NOW), NOW)
    last_equity_day = conn.execute(
        "SELECT max(day) FROM backtest_trade t JOIN backtest_run r USING (run_id)"
    ).fetchone()[0]
    assert last_equity_day < DAYS[270]  # no trade on or after the holdout's first day
    exp = conn.execute(
        "SELECT holdout_opened_at FROM experiment WHERE experiment_id=%s", (sid,)
    ).fetchone()
    assert exp == (None,)
    assert all(t["metrics"]["days"] <= 270 for t in study_jobs.trials(conn, sid))


def test_a_rerun_skips_trials_already_done_and_a_second_job_cannot_start_while_one_is_active(env):
    conn, owner = env
    sid = registered(conn, owner)
    first = study_jobs.enqueue(conn, sid, owner, NOW)
    with pytest.raises(study_jobs.JobError, match="already"):
        study_jobs.enqueue(conn, sid, owner, NOW)
    run_study(conn, first, NOW)
    before = [(t["trial_id"], t["seconds"]) for t in study_jobs.trials(conn, sid)]
    second = study_jobs.enqueue(conn, sid, owner, NOW)  # fine now: the first finished
    run_study(conn, second, NOW)
    assert [
        (t["trial_id"], t["seconds"]) for t in study_jobs.trials(conn, sid)
    ] == before  # nothing was run twice
    assert registry.trial_count(conn, sid) == 2


def test_a_job_is_claimed_by_one_worker_and_progress_is_visible_while_it_runs(env):
    conn, owner = env
    sid = registered(conn, owner)
    rid = study_jobs.enqueue(conn, sid, owner, NOW)
    assert study_jobs.get_run(conn, rid)["status"] == "QUEUED"
    claimed = study_jobs.claim(conn, NOW)
    assert claimed == rid and study_jobs.claim(conn, NOW) is None  # nobody else gets it
    assert study_jobs.get_run(conn, rid)["status"] == "RUNNING"
    run_study(conn, rid, NOW)
    assert study_jobs.get_run(conn, rid)["status"] == "DONE"
    assert (
        study_jobs.latest_run(conn, sid)["run_id"] == rid
        and study_jobs.latest_run(conn, 99999) is None
    )


def test_a_trial_that_fails_is_recorded_with_its_reason_and_the_job_says_failed(env, monkeypatch):
    conn, owner = env
    sid = registered(conn, owner)
    rid = study_jobs.enqueue(conn, sid, owner, NOW)
    from algo.research import study_runner

    def boom(*a, **k):
        raise RuntimeError("the engine fell over")

    monkeypatch.setattr(study_runner, "run_backtest", boom)
    run_study(conn, rid, NOW)
    run = study_jobs.get_run(conn, rid)
    assert run["status"] == "FAILED" and "the engine fell over" in run["error"]
    assert [t["status"] for t in study_jobs.trials(conn, sid)] == [
        "FAILED"
    ]  # it stops at the first failure
    assert registry.trial_count(conn, sid) == 0  # a failed trial is not counted


def test_a_study_without_a_universe_or_without_prices_stops_with_a_clear_reason(env):
    conn, owner = env
    sid = registered(
        conn, owner, universe={"segments": ["micro"], "min_history_sessions": 110}, name="nobody"
    )
    run_study(conn, study_jobs.enqueue(conn, sid, owner, NOW), NOW)
    run = study_jobs.latest_run(conn, sid)
    assert run["status"] == "FAILED" and "no stocks" in run["error"]
    with pytest.raises(StudyRunError, match="no such run"):
        run_study(conn, 424242, NOW)


def test_jobs_can_be_cancelled_before_they_start_and_listed_by_study(env):
    conn, owner = env
    sid = registered(conn, owner)
    rid = study_jobs.enqueue(conn, sid, owner, NOW)
    study_jobs.cancel(conn, rid, NOW)
    assert study_jobs.get_run(conn, rid)["status"] == "CANCELLED"
    with pytest.raises(study_jobs.JobError, match="cannot be cancelled"):
        study_jobs.cancel(conn, rid, NOW)
    run_study(conn, rid, NOW)  # a cancelled job is not run
    assert study_jobs.trials(conn, sid) == []
    with pytest.raises(study_jobs.JobError, match="no such study"):
        study_jobs.enqueue(conn, 31337, owner, NOW)


def test_the_daily_returns_of_every_finished_trial_are_kept_for_the_validation_steps(env):
    conn, owner = env
    sid = registered(conn, owner)
    run_study(conn, study_jobs.enqueue(conn, sid, owner, NOW), NOW)
    kept = study_jobs.trial_returns(conn, sid)
    assert len(kept) == 2 and all(
        len(r) >= 100 and all(isinstance(x, float) for x in r) for r in kept.values()
    )
    from algo.research.study_runner import _returns  # noqa: F401  (the same series the metrics were computed from)

    first = study_jobs.trials(conn, sid)[0]
    assert (
        kept[first["params_hash"]]
        and first["metrics"]["days"] == len(kept[first["params_hash"]]) + 1
    )
