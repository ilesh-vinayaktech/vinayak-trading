"""Running a registered study's trials through the real engine, one parameter combination at a time, on synthetic prices.
ENGINEERING_TEST_ONLY data: nothing here is a strategy result."""

import math
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
from algo.research import study_jobs, study_runner
from algo.research.study_runner import StudyRunError, run_study
from algo.research.study_store import register_study
from tests.support.portal import add_user
from tests.support.research_lock import anchor_open_lock
from tests.unit.research.test_study import spec

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)
N = 330  # sessions of data
FIRST = date(2024, 1, 1)


def sessions(n=N, first=FIRST):
    out, d = [], first
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


DAYS = sessions()


def sawtooth(k, days=DAYS):
    """Rises 0.4% a day; every 30 sessions (staggered by k) it drops 3% a day for four days."""
    p, out = D(100), {}
    for i, d in enumerate(days):
        out[d] = p
        p *= D("0.97") if i >= 150 and (i + k) % 30 < 4 else D("1.004")
    return out


def build_env(conn, days, list_date=date(2023, 6, 30)):
    migrate(conn)
    anchor_open_lock(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    ids = []
    rows = []
    for k in range(8):
        iid = repo.add_instrument(x, f"S{k}", isin=f"INE00000000{k}")
        ids.append(iid)
        rows.append(CapRow(k + 1, f"INE00000000{k}", f"S{k}", f"Co {k}", D(1000 - k)))
        for d, p in sawtooth(k, days).items():
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
                    days[-1],
                    NOW,
                ),
            )
    load_list(
        conn, CapList(list_date, tuple(rows)), "u", "s", NOW
    )  # all eight are large caps, in force from 2023-08-01
    freeze.take(conn, "kite", days[-1], datetime(2026, 11, 12, tzinfo=UTC), "synthetic reference")
    schedule_store.import_files(conn, Path("config/cost_schedules"), now=NOW)
    owner = add_user(conn, SimClock(NOW), "TRADER", "jane@example.com")
    return conn, owner


@pytest.fixture
def env(conn):
    return build_env(conn, DAYS)


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


def test_the_studys_order_size_limits_reach_the_engine_and_are_kept_with_the_run(env):
    conn, owner = env
    sid = registered(conn, owner, min_order_value="2000", max_order_value="50000")
    run_study(conn, study_jobs.enqueue(conn, sid, owner, NOW), NOW)
    cfg = conn.execute("SELECT config FROM backtest_run ORDER BY run_id LIMIT 1").fetchone()[0]
    assert (cfg["min_order_value"], cfg["max_order_value"]) == ("2000", "50000")
    prices = conn.execute(
        "SELECT qty*price FROM backtest_trade WHERE side='BUY' AND qty*price < 2000 LIMIT 1"
    ).fetchall()
    assert prices == []  # no buy below the minimum


# ---- the verdict: walk-forward and every gate over the finished trials -------------------------------------

LONG = sessions(
    1000, date(2021, 1, 4)
)  # enough research days (about 760) for two walk-forward windows


def long_spec(**over):
    base = {
        "name": "long", "universe": {"segments": ["large"], "min_history_sessions": 110},
        "grid": {"trend_sma": [100], "entry_rsi": [25, 30], "exit_rsi": [60], "max_positions": [5]},
        "start": LONG[0].isoformat(), "end": LONG[-1].isoformat(), "holdout_start": LONG[940].isoformat(),
        "accept_survivorship_bias": True, "capital": "1000000",
    }  # fmt: skip
    return spec(**{**base, **over})


@pytest.fixture
def long_env(conn):
    return build_env(conn, LONG, date(2020, 6, 30))


def judge(conn, owner, sid):
    from algo.research.study_runner import execute

    rid = study_jobs.enqueue(conn, sid, owner, NOW, kind="verdict")
    execute(conn, rid, NOW)
    return study_jobs.get_run(conn, rid)


def test_the_verdict_runs_every_gate_over_the_trials_and_keeps_the_report_and_the_stress_runs(
    long_env,
):
    conn, owner = long_env
    sid = register_study(conn, owner, long_spec(), NOW)
    run_study(conn, study_jobs.enqueue(conn, sid, owner, NOW), NOW)
    run = judge(conn, owner, sid)
    assert (run["kind"], run["status"], run["error"]) == ("verdict", "DONE", None)
    rep = conn.execute(
        "SELECT passed, thresholds_status, n_trials, evidence, gates, refs, run_id FROM validation_report WHERE experiment_id=%s",
        (sid,),
    ).fetchone()
    passed, status, n, evidence, gates, refs, base_run = rep
    assert status == "confirmed" and n == 2 and len(gates) == 14
    assert {g["name"] for g in gates} >= {
        "oos_sharpe",
        "deflated_sharpe",
        "survives_2x_costs",
        "survives_3x_capital",
    }
    assert evidence["oos_days"] == 2 * 126 and evidence["sharpe_2x_costs"] is not None
    assert evidence["sharpe_3x_capital"] is not None and evidence["pbo"] is not None
    assert len(refs["windows"]) == 2 and refs["chosen"] in study_jobs_params(conn, sid)
    trial_runs = {t["backtest_run"] for t in study_jobs.trials(conn, sid)}
    assert base_run in trial_runs and {refs["cost_2x_run"], refs["capital_run"]}.isdisjoint(
        trial_runs
    )
    assert registry.trial_count(conn, sid) == 2  # the stress runs are not trials
    labels = dict(conn.execute("SELECT run_id, label FROM backtest_run WHERE run_id = ANY(%s)", ([refs["cost_2x_run"], refs["capital_run"], base_run],)).fetchall())  # fmt: skip
    assert labels == {
        refs["cost_2x_run"]: "verdict: 2x costs",
        refs["capital_run"]: "verdict: 3x capital",
        base_run: None,
    }
    by = {g["name"]: g for g in gates}
    assert (
        by["beats_benchmark"]["detail"] == "evidence missing"
        and "no benchmark called" in refs["benchmark_note"]
    )
    assert passed is False  # missing evidence fails


def test_the_verdict_counts_every_trial_of_the_family_not_just_this_studys(long_env):
    conn, owner = long_env
    sibling = registry.register(
        conn, name="an earlier idea in the same family", strategy_id="trend_pullback", hypothesis="x" * 30,
        style="long_only", param_ranges={"a": [1, 100]}, holdout=(NOW.date(), NOW.date()), now=NOW, family_id=1,
    )  # fmt: skip
    for i, sharpe in enumerate((0.01, 0.02, 0.03)):
        registry.record_trial(conn, sibling, {"a": i + 1}, sharpe, None, NOW)
    sid = register_study(conn, owner, long_spec(), NOW)  # also family 1
    run_study(conn, study_jobs.enqueue(conn, sid, owner, NOW), NOW)
    assert judge(conn, owner, sid)["status"] == "DONE"
    own = registry.trial_count(conn, sid)
    n = conn.execute(
        "SELECT n_trials FROM validation_report WHERE experiment_id=%s", (sid,)
    ).fetchone()[0]
    assert own == 2 and n == own + 3 == registry.family_trial_count(
        conn, 1
    )  # the deflation follows the whole family


def study_jobs_params(conn, sid):
    return [t["params"] for t in study_jobs.trials(conn, sid)]


@pytest.fixture(autouse=True)
def gate_off(monkeypatch, tmp_path):
    monkeypatch.setattr(study_runner, "GATE_FILE", tmp_path / "no_gate.json")


def _benchmark_study(long_env):
    from algo.data.benchmark import DEFAULT_BENCHMARK, ingest, register, store_validation

    conn, owner = long_env
    bid = register(conn, name=DEFAULT_BENCHMARK, provider="p", index_symbol="N200TRI", return_type="TOTAL_RETURN", methodology_version="m")  # fmt: skip
    ingest(conn, bid, [(d, D(1000) * (1 + D("0.0003") * i + D(str(0.01 * math.sin(i))))) for i, d in enumerate(LONG)], source="s", source_timestamp=NOW, raw_hash="h", now=NOW)  # fmt: skip
    store_validation(conn, bid, report={"report_version": "2", "technical_validation_passed": True, "check_states": {}}, passed=True, normalized_sha256="n", factsheet_sha256=None, unresolved=[], now=NOW)  # fmt: skip
    sid = register_study(conn, owner, long_spec(), NOW)
    run_study(conn, study_jobs.enqueue(conn, sid, owner, NOW), NOW)
    assert judge(conn, owner, sid)["status"] == "DONE"
    return conn, bid, sid


def test_with_the_gate_on_a_benchmark_the_release_does_not_call_eligible_fails_its_gates_and_says_why(
    long_env, monkeypatch, tmp_path
):
    from types import SimpleNamespace

    gate = tmp_path / "gate.json"
    gate.write_text('{"enabled": true}')
    monkeypatch.setattr(study_runner, "GATE_FILE", gate)
    found = {
        "series": "B1_X",
        "uses": {"BENCHMARK_GATE": {"eligible": False, "blockers": ["U06: x"]}},
    }
    monkeypatch.setattr(
        study_runner.artifacts,
        "load",
        lambda docs: SimpleNamespace(version="9.9", eligibility_of=lambda i: found),
    )
    conn, _bid, sid = _benchmark_study(long_env)
    refs = conn.execute(
        "SELECT refs FROM validation_report WHERE experiment_id=%s", (sid,)
    ).fetchone()[0]
    assert (
        "not BENCHMARK_GATE_ELIGIBLE in release 9.9" in refs["benchmark_note"]
        and "U06: x" in refs["benchmark_note"]
    )


def test_with_the_gate_on_an_eligible_benchmark_supplies_the_evidence(
    long_env, monkeypatch, tmp_path
):
    from types import SimpleNamespace

    gate = tmp_path / "gate.json"
    gate.write_text('{"enabled": true}')
    monkeypatch.setattr(study_runner, "GATE_FILE", gate)
    found = {"series": "B1_X", "uses": {"BENCHMARK_GATE": {"eligible": True, "blockers": []}}}
    monkeypatch.setattr(
        study_runner.artifacts,
        "load",
        lambda docs: SimpleNamespace(version="9.9", eligibility_of=lambda i: found),
    )
    conn, _bid, sid = _benchmark_study(long_env)
    refs = conn.execute(
        "SELECT refs FROM validation_report WHERE experiment_id=%s", (sid,)
    ).fetchone()[0]
    assert refs["benchmark_note"] is None


def test_a_validated_benchmark_supplies_the_benchmark_evidence(long_env):
    from algo.data.benchmark import DEFAULT_BENCHMARK, ingest, register, store_validation

    conn, owner = long_env
    bid = register(conn, name=DEFAULT_BENCHMARK, provider="p", index_symbol="N200TRI", return_type="TOTAL_RETURN", methodology_version="m")  # fmt: skip
    ingest(conn, bid, [(d, D(1000) * (1 + D("0.0003") * i + D(str(0.01 * math.sin(i))))) for i, d in enumerate(LONG)], source="s", source_timestamp=NOW, raw_hash="h", now=NOW)  # fmt: skip
    store_validation(conn, bid, report={"report_version": "2", "technical_validation_passed": True, "check_states": {}}, passed=True, normalized_sha256="n", factsheet_sha256=None, unresolved=[], now=NOW)  # fmt: skip
    sid = register_study(conn, owner, long_spec(), NOW)
    run_study(conn, study_jobs.enqueue(conn, sid, owner, NOW), NOW)
    assert judge(conn, owner, sid)["status"] == "DONE"
    evidence, refs = conn.execute(
        "SELECT evidence, refs FROM validation_report WHERE experiment_id=%s", (sid,)
    ).fetchone()
    assert refs["benchmark_note"] is None
    assert (
        evidence["benchmark_sharpe"] is not None and evidence["benchmark_max_drawdown"] is not None
    )


def test_a_verdict_before_the_trials_are_done_or_on_too_little_history_stops_with_the_reason(
    env,
):
    conn, owner = env  # 330 sessions: far too short for walk-forward
    sid = register_study(conn, owner, small_spec(), NOW)
    early = judge(conn, owner, sid)
    assert early["status"] == "FAILED" and "run all trials first" in early["error"]
    run_study(conn, study_jobs.enqueue(conn, sid, owner, NOW), NOW)
    short = judge(conn, owner, sid)
    assert short["status"] == "FAILED" and "too short for walk-forward" in short["error"]
    assert conn.execute("SELECT count(*) FROM validation_report").fetchone() == (0,)


# ---- the holdout: opened once, only after a passing verdict ---------------------------------------------------

CHOSEN = {"trend_sma": 100, "entry_rsi": 25, "exit_rsi": 60, "max_positions": 5}


def with_report(conn, sid, *, passed):
    from algo.backtest.validation.gates import Evidence, Thresholds, evaluate

    base = conn.execute(
        "INSERT INTO backtest_run (strategy_id,strategy_version,params,params_hash,code_version,reader_mode,config,"
        "cost_model,adjustment_versions,provisional_events,unapplied_events,blocked_instruments,unmodelled_events,"
        "accounting_complete,dividends_received,metrics,result_hash,created_at,ledger_reconciled,reconciliation,pnl)"
        " VALUES ('trend_pullback','1','{}','ph','c','research','{}','{}','{}','[]','[]','[]','[]',true,0,'{}','rh',%s,true,'{}','{}')"
        " RETURNING run_id", (NOW,)).fetchone()[0]  # fmt: skip
    ev = Evidence()
    rid = registry.save_report(
        conn,
        sid,
        base,
        evaluate(ev, Thresholds(*([0.0] * 12)), "confirmed"),
        ev,
        2,
        NOW,
        refs={"chosen": CHOSEN},
    )
    conn.execute("UPDATE validation_report SET passed=%s WHERE report_id=%s", (passed, rid))


def open_it(conn, owner, sid):
    from algo.research.study_runner import execute

    rid = study_jobs.enqueue(conn, sid, owner, NOW, kind="holdout")
    execute(conn, rid, NOW)
    return study_jobs.get_run(conn, rid)


def test_the_holdout_runs_the_chosen_settings_once_on_the_days_the_study_never_saw(long_env):
    conn, owner = long_env
    sid = register_study(conn, owner, long_spec(), NOW)
    with_report(conn, sid, passed=True)
    run = open_it(conn, owner, sid)
    assert (run["kind"], run["status"], run["error"]) == ("holdout", "DONE", None)
    res = study_jobs.holdout_result(conn, sid)
    assert [g["name"] for g in res["gates"]] == [
        "holdout_sharpe",
        "holdout_drawdown",
        "holdout_beats_benchmark",
    ]
    assert res["refs"]["window"][0] >= LONG[940].isoformat() and res["refs"]["chosen"] == CHOSEN
    assert res["evidence"]["days"] > 20 and "no benchmark called" in res["refs"]["benchmark_note"]
    assert res["passed"] is False  # no index loaded: that gate fails for missing evidence
    opened, holdout_run = conn.execute(
        "SELECT holdout_opened_at, holdout_run_id FROM experiment WHERE experiment_id=%s", (sid,)
    ).fetchone()
    assert opened is not None and holdout_run == res["run_id"]
    first_day = conn.execute(
        "SELECT min(day) FROM backtest_trade WHERE run_id=%s", (res["run_id"],)
    ).fetchone()[0]
    assert first_day is None or first_day >= LONG[940]  # nothing traded before the holdout
    assert registry.trial_count(conn, sid) == 0  # it is not a trial
    again = open_it(conn, owner, sid)
    assert again["status"] == "FAILED" and "already been opened" in again["error"]
    assert conn.execute("SELECT count(*) FROM study_holdout").fetchone() == (1,)


def test_the_holdout_stays_closed_without_a_passing_research_verdict(long_env):
    conn, owner = long_env
    sid = register_study(conn, owner, long_spec(), NOW)
    none = open_it(conn, owner, sid)
    assert none["status"] == "FAILED" and "passed every check" in none["error"]
    with_report(conn, sid, passed=False)
    failed = open_it(conn, owner, sid)
    assert failed["status"] == "FAILED" and "passed every check" in failed["error"]
    opened = conn.execute(
        "SELECT holdout_opened_at FROM experiment WHERE experiment_id=%s", (sid,)
    ).fetchone()
    assert opened == (None,) and study_jobs.holdout_result(conn, sid) is None


def test_progress_is_written_at_most_every_two_seconds_and_always_on_the_last_day(env, monkeypatch):
    from algo.research import study_runner

    conn, owner = env
    sid = registered(conn, owner)
    rid = study_jobs.enqueue(conn, sid, owner, NOW)
    clock = iter([100.0, 100.5, 101.0, 102.5, 102.6, 103.0])
    monkeypatch.setattr(study_runner.time, "monotonic", lambda: next(clock))
    tick = study_runner._ticker(conn, rid)
    seen = []
    for i in (1, 2, 3, 4, 5, 6):
        tick(i, 6, DAYS[i])
        run = study_jobs.get_run(conn, rid)
        seen.append((run["step_done"], run["step_total"]))
    # written on day 1 (first), not on 2-3 (under 2 s later), on day 4 (2.5 s after day 1), not on 5, and always on the last day
    assert seen == [(1, 6), (1, 6), (1, 6), (4, 6), (4, 6), (6, 6)]
    study_jobs.progress(conn, rid, 1, None)
    assert (
        study_jobs.get_run(conn, rid)["step_done"],
        study_jobs.get_run(conn, rid)["step_total"],
    ) == (0, 0)


def test_a_finished_run_leaves_no_half_done_counter_behind(env):
    conn, owner = env
    sid = registered(conn, owner)
    rid = study_jobs.enqueue(conn, sid, owner, NOW)
    run_study(conn, rid, NOW)
    run = study_jobs.get_run(conn, rid)
    assert (run["status"], run["step_done"], run["step_total"]) == ("DONE", 0, 0)


# ---- stopping a job that has already started ------------------------------------------------------------------


def test_a_stop_requested_before_the_first_day_ends_the_run_cancelled_with_nothing_saved_half_done(
    env,
):
    conn, owner = env
    sid = registered(conn, owner)
    rid = study_jobs.enqueue(conn, sid, owner, NOW)
    study_jobs.cancel(conn, rid, NOW)  # not started yet: simply cancelled
    assert study_jobs.get_run(conn, rid)["status"] == "CANCELLED"
    rid2 = study_jobs.enqueue(conn, sid, owner, NOW)
    study_jobs.claim(conn, NOW)  # a worker has it: RUNNING
    study_jobs.cancel(conn, rid2, NOW)
    assert (
        study_jobs.get_run(conn, rid2)["status"] == "RUNNING"
        and study_jobs.get_run(conn, rid2)["cancel_requested"]
    )
    run_study(conn, rid2, NOW)
    run = study_jobs.get_run(conn, rid2)
    assert (run["status"], run["error"], run["finished_at"] is not None) == (
        "CANCELLED",
        None,
        True,
    )
    assert (
        study_jobs.trials(conn, sid) == []
    )  # the trial that was interrupted is not recorded, not even as failed
    assert registry.trial_count(conn, sid) == 0
    assert study_jobs.enqueue(conn, sid, owner, NOW)  # the study is free for a new run


def test_stopping_between_trials_keeps_the_finished_ones_and_a_rerun_carries_on(env, monkeypatch):
    conn, owner = env
    sid = registered(conn, owner)
    rid = study_jobs.enqueue(conn, sid, owner, NOW)
    real = study_jobs.save_trial

    def save_then_stop(*a, **kw):
        real(*a, **kw)
        conn.execute("UPDATE study_run SET cancel_requested=true WHERE run_id=%s", (rid,))

    monkeypatch.setattr(study_jobs, "save_trial", save_then_stop)
    run_study(conn, rid, NOW)
    assert study_jobs.get_run(conn, rid)["status"] == "CANCELLED"
    assert [t["status"] for t in study_jobs.trials(conn, sid)] == [
        "DONE"
    ]  # the first trial finished and stays
    monkeypatch.setattr(study_jobs, "save_trial", real)
    again = study_jobs.enqueue(conn, sid, owner, NOW)
    run_study(conn, again, NOW)
    assert study_jobs.get_run(conn, again)["status"] == "DONE"
    assert [t["status"] for t in study_jobs.trials(conn, sid)] == [
        "DONE",
        "DONE",
    ]  # only the missing one was run


def test_stopping_a_holdout_before_it_ends_leaves_the_holdout_unopened(long_env):
    conn, owner = long_env
    sid = register_study(conn, owner, long_spec(), NOW)
    with_report(conn, sid, passed=True)
    rid = study_jobs.enqueue(conn, sid, owner, NOW, kind="holdout")
    conn.execute("UPDATE study_run SET cancel_requested=true WHERE run_id=%s", (rid,))
    from algo.research.study_runner import execute

    execute(conn, rid, NOW)
    assert study_jobs.get_run(conn, rid)["status"] == "CANCELLED"
    assert conn.execute(
        "SELECT holdout_opened_at FROM experiment WHERE experiment_id=%s", (sid,)
    ).fetchone() == (None,)
    assert study_jobs.holdout_result(conn, sid) is None


def test_a_screener_study_runs_through_the_real_engine_and_buys_what_the_screen_picks(env):
    conn, owner = env
    screen = {"conditions": [{"field": "chg_3m", "op": "gt", "value": 0}], "sort": "chg_3m"}
    sid = registered(
        conn, owner, strategy_id="screener", grid={"max_positions": [5]}, screen=screen
    )
    rid = study_jobs.enqueue(conn, sid, owner, NOW)
    run_study(conn, rid, NOW)
    run = study_jobs.get_run(conn, rid)
    assert (run["status"], run["error"]) == ("DONE", None)
    (t,) = study_jobs.trials(conn, sid)
    assert t["status"] == "DONE" and t["metrics"]["trades"] > 0


def test_a_study_that_reaches_into_the_global_holdout_is_not_run_and_the_reader_it_gets_is_the_guard(
    env, monkeypatch, tmp_path
):
    from algo.research import holdout_lock
    from algo.research.holdout_lock import Lock, ResearchReader
    from tests.support.research_lock import write_lock_file

    conn, owner = env
    sid = registered(conn, owner)  # registered under the open test lock
    spec_ = small_spec()
    # the real window: development ends before this study's last day
    narrow = Lock(DAYS[-3], DAYS[-2], DAYS[-1])
    monkeypatch.setattr(
        holdout_lock, "LOCK_FILE", write_lock_file(tmp_path / "narrow.json", narrow)
    )
    holdout_lock.anchor(conn, narrow, by="test", reason="narrow window", now=NOW)
    with pytest.raises(StudyRunError, match="inside the global research holdout"):
        study_runner.prepare(conn, spec_, sid)
    # a study that ends in development gets the guard, not a bare BarReader
    setup = study_runner.prepare(conn, small_spec(end=DAYS[-4].isoformat()), sid)
    assert isinstance(setup.reader, ResearchReader)


def test_the_studys_filing_lag_reaches_the_fundamentals_book_in_research_and_in_the_holdout_evaluator(
    env, monkeypatch
):
    conn, owner = env
    seen = []
    monkeypatch.setattr(
        study_runner.fundamentals_book,
        "load",
        lambda *a, **k: seen.append((a[3], k.get("lag"))) or None,
    )
    screen = {
        "conditions": [{"field": "pe", "op": "lt", "value": 15}],
        "sort": "pe",
        "descending": False,
    }
    sid = registered(
        conn,
        owner,
        strategy_id="screener",
        grid={"max_positions": [5]},
        screen=screen,
        filing_lag_days=7,
    )
    study_runner.prepare(
        conn,
        small_spec(
            strategy_id="screener", grid={"max_positions": [5]}, screen=screen, filing_lag_days=7
        ),
        sid,
    )
    assert [lag for _, lag in seen] == [timedelta(days=7)]
    seen.clear()
    sid0 = registered(
        conn,
        owner,
        name="nolag",
        strategy_id="screener",
        grid={"max_positions": [5]},
        screen=screen,
    )
    study_runner.prepare(
        conn,
        small_spec(
            name="nolag", strategy_id="screener", grid={"max_positions": [5]}, screen=screen
        ),
        sid0,
    )
    assert [lag for _, lag in seen] == [
        timedelta(0)
    ]  # studies registered before the field existed keep running exactly as they did


def test_a_registered_definition_runs_through_the_study_and_its_trials_are_counted(env):
    from algo.factory import generate

    conn, owner = env
    defn = generate.definition_for(
        generate.Hypothesis(1, 1, "ret_20d", "1", 20, "POSITIVE", 0.05, 0.001)
    )
    sid = registered(
        conn,
        owner,
        name="dsl tiny",
        strategy_id="dsl",
        definition=defn.canonical(),
        grid={"entry_share": [30, 60], "max_positions": [4]},
    )
    run_study(conn, study_jobs.enqueue(conn, sid, owner, NOW), NOW)
    trials = study_jobs.trials(conn, sid)
    assert [t["params"]["entry_share"] for t in trials] == [30, 60]
    assert all(t["status"] == "DONE" and t["metrics"]["trades"] > 0 for t in trials)
    assert registry.trial_count(conn, sid) == 2
    locked = conn.execute("SELECT study FROM experiment WHERE experiment_id=%s", (sid,)).fetchone()[
        0
    ]
    assert locked["spec"]["definition"]["strategy_id"] == "ALPHA_RET_20D_H20"


def test_a_study_is_built_from_a_registered_definition_and_registered(env):
    from algo.factory import generate
    from algo.factory import registry as freg
    from algo.factory import study as fstudy

    conn, owner = env
    defn = generate.definition_for(
        generate.Hypothesis(1, 1, "ret_20d", "1", 20, "POSITIVE", 0.05, 0.001)
    )
    freg.register(conn, defn, by="t", reason="test", now=NOW)
    s = fstudy.spec_for(
        conn, defn.strategy_id, 1, family_id=1, start=DAYS[0], end=DAYS[-1], holdout_start=DAYS[270]
    )
    assert (s.strategy_id, s.definition, s.grid) == ("dsl", defn.canonical(), fstudy.GRID)
    sid = fstudy.register(conn, owner, s, NOW)
    assert registry.trial_count(conn, sid) == 0 and sid > 0


def test_starting_a_definitions_study_registers_it_once_and_queues_its_trials(env):
    from algo.factory import generate
    from algo.factory import registry as freg
    from algo.factory import study as fstudy

    conn, owner = env
    defn = generate.definition_for(
        generate.Hypothesis(1, 1, "ret_20d", "1", 20, "POSITIVE", 0.05, 0.001)
    )
    freg.register(conn, defn, by="t", reason="test", now=NOW)
    eid, run = fstudy.start(conn, owner, defn.strategy_id, 1, NOW)
    assert study_jobs.get_run(conn, run)["status"] == "QUEUED"
    with pytest.raises(study_jobs.JobError, match="already"):
        fstudy.start(conn, owner, defn.strategy_id, 1, NOW)  # one active run at a time
    conn.execute("UPDATE study_run SET status='CANCELLED' WHERE run_id=%s", (run,))
    again, _ = fstudy.start(conn, owner, defn.strategy_id, 1, NOW)
    assert again == eid  # the same study, not a second one


def test_a_study_with_the_per_trade_stop_runs_and_records_it_in_its_locked_document(env):
    conn, owner = env
    sid = registered(conn, owner, name="with stop", trade_stop="0.02", stop_cooldown_days=5)
    run_study(conn, study_jobs.enqueue(conn, sid, owner, NOW), NOW)
    assert all(t["status"] == "DONE" for t in study_jobs.trials(conn, sid))
    locked = conn.execute("SELECT study FROM experiment WHERE experiment_id=%s", (sid,)).fetchone()[
        0
    ]
    assert locked["spec"]["trade_stop"] == "0.02" and locked["spec"]["stop_cooldown_days"] == 5


def test_a_fixed_setting_study_runs_every_trial_and_judges_only_the_pre_registered_setting(env):
    from algo.factory import generate
    from algo.factory import registry as freg
    from algo.factory import study as fstudy

    conn, owner = env
    defn = generate.definition_for(
        generate.Hypothesis(1, 1, "ret_20d", "1", 20, "POSITIVE", 0.05, 0.001)
    )
    freg.register(conn, defn, by="t", reason="test", now=NOW)
    s = fstudy.spec_for(
        conn,
        defn.strategy_id,
        1,
        family_id=1,
        start=DAYS[0],
        end=DAYS[-1],
        holdout_start=DAYS[270],
        fixed=True,
    )
    assert s.fixed == {"max_positions": 20, "exit_share": 50} and s.name.endswith("stop2 fixed")
    assert s.fixed in [
        dict(c)
        for c in __import__("algo.research.study", fromlist=["combinations"]).combinations(s)
    ]


def test_a_fixed_study_uses_the_definitions_own_numbers_and_a_robustness_grid_never_picks_a_replacement(
    env,
):
    from algo.factory import generate, preregistered
    from algo.factory import registry as freg
    from algo.factory import study as fstudy

    conn, owner = env
    gen = generate.definition_for(
        generate.Hypothesis(1, 1, "ret_20d", "1", 20, "POSITIVE", 0.05, 0.001)
    )
    mom = preregistered.definitions()[0]  # written down with 15 stocks
    for d in (gen, mom):
        freg.register(conn, d, by="t", reason="test", now=NOW)
    g = fstudy.spec_for(
        conn,
        gen.strategy_id,
        1,
        family_id=1,
        start=DAYS[0],
        end=DAYS[-1],
        holdout_start=DAYS[270],
        fixed=True,
    )
    m = fstudy.spec_for(
        conn,
        mom.strategy_id,
        1,
        family_id=1,
        start=DAYS[0],
        end=DAYS[-1],
        holdout_start=DAYS[270],
        fixed=True,
    )
    assert (g.fixed, g.grid) == (
        {"max_positions": 20, "exit_share": 50},
        {"max_positions": [10, 20, 30], "exit_share": [30, 50, 70]},
    )
    assert (m.fixed, m.grid) == (
        {"max_positions": 15, "exit_share": 50},
        {"max_positions": [5, 15, 25], "exit_share": [30, 50, 70]},
    )  # the momentum rule's own 15, not a borrowed 20
    # once the primary setting has a verdict, a different fixed setting for the same definition, window and stop is refused
    eid = fstudy.register(conn, owner, g, NOW)
    run_study(conn, study_jobs.enqueue(conn, eid, owner, NOW), NOW)
    run_id = conn.execute(
        "SELECT backtest_run FROM study_trial WHERE experiment_id=%s AND backtest_run IS NOT NULL LIMIT 1",
        (eid,),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO validation_report (experiment_id, run_id, passed, thresholds_status, n_trials, evidence, gates, created_at) VALUES (%s,%s,FALSE,'confirmed',9,'{}','[]',%s)",
        (eid, run_id, NOW),
    )  # a verdict exists (its content does not matter to the guard)
    other = g.model_copy(
        update={"fixed": {"max_positions": 30, "exit_share": 50}, "name": "chosen after the fact"}
    )
    with pytest.raises(fstudy.ReplacementRefused, match="cannot be chosen after it"):
        fstudy.register(conn, owner, other, NOW)
    same_again = g.model_copy(update={"name": "the same setting again"})
    assert (
        fstudy.register(conn, owner, same_again, NOW) > eid
    )  # the same setting is fine: it is not a replacement


def test_the_runs_of_one_study_load_each_stocks_data_once_and_give_exactly_the_same_results(
    env, monkeypatch
):
    """Studies run the same strategy many times over the same frozen data (every setting, then the stress runs): loading and the day's features are shared, and the numbers do not change."""
    from algo.factory import generate
    from algo.factory import registry as freg
    from algo.factory import study as fstudy
    from algo.research import study_runner as sr

    conn, owner = env
    defn = generate.definition_for(
        generate.Hypothesis(1, 1, "ret_20d", "1", 20, "POSITIVE", 0.05, 0.001)
    )
    freg.register(conn, defn, by="t", reason="test", now=NOW)
    s = fstudy.spec_for(
        conn,
        defn.strategy_id,
        1,
        family_id=1,
        start=DAYS[0],
        end=DAYS[-1],
        holdout_start=DAYS[270],
        fixed=True,
    )
    eid = fstudy.register(conn, owner, s, NOW)
    setup = sr.prepare(conn, s, eid)
    loads = []
    inner = type(
        setup.reader._inner
    )  # the BarReader under the guard: every real read from the database goes through it
    real = inner.load

    def counting(self, iid, *, strict=False):
        loads.append(iid)
        return real(self, iid, strict=strict)

    monkeypatch.setattr(inner, "load", counting)
    combo = {"max_positions": 10, "exit_share": 50}
    cfg = sr.BacktestConfig(
        start=setup.begin, end=setup.research_end, initial_cash=s.capital, cost=setup.policy
    )
    first = sr.run_backtest(conn, sr.build(s, combo, setup), cfg, reader=setup.reader)
    after_first = len(loads)
    again = sr.run_backtest(conn, sr.build(s, combo, setup), cfg, reader=setup.reader)
    assert [e for e in again.equity] == [e for e in first.equity] and len(again.trades) == len(
        first.trades
    )  # identical
    assert len(loads) == after_first  # the second run asked the reader for nothing new


def test_a_study_on_the_swing_score_runs_through_the_real_engine_and_records_which_scores_it_read(
    env,
):
    conn, owner = env
    for (iid,) in conn.execute(
        "SELECT instrument_id FROM instrument WHERE asset_class='equity'"
    ).fetchall():
        for d in DAYS[::5]:  # a weekly row per stock, as the backfill writes them
            conn.execute(
                "INSERT INTO stock_score_history (day, instrument_id, score) VALUES (%s,%s,%s)",
                (d, iid, 70 + iid % 20),
            )
    screen = {"conditions": [{"field": "score", "op": "gt", "value": 60}], "sort": "score"}
    sid = registered(
        conn, owner, strategy_id="screener", grid={"max_positions": [5]}, screen=screen
    )
    rid = study_jobs.enqueue(conn, sid, owner, NOW)
    run_study(conn, rid, NOW)
    run = study_jobs.get_run(conn, rid)
    assert (run["status"], run["error"]) == ("DONE", None)
    (t,) = study_jobs.trials(conn, sid)
    assert t["status"] == "DONE" and t["metrics"]["trades"] > 0
    assert (
        len(run["detail"]["score_digest"]) == 64
    )  # the run says exactly which scores it read, so a rebuilt history cannot change it silently
