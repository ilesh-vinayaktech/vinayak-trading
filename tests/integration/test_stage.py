"""A saved strategy's stage: the allowed moves, the gate for LIVE, and the append-only record."""

from datetime import UTC, datetime

import psycopg
import pytest

from algo.backtest.validation.gates import Evidence, Thresholds, evaluate
from algo.backtest.validation.registry import register, save_report
from algo.core.clock import SimClock
from algo.data.store.migrate import migrate
from algo.paper import configs
from algo.strategy import stage
from tests.support.portal import add_user

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)


@pytest.fixture
def env(conn):
    migrate(conn)
    owner = add_user(conn, SimClock(NOW), "TRADER", "jane@example.com")
    cid = configs.create(conn, owner, name="Mine", universe="nifty200", max_instruments=None,
                         timeframe="1D", params={"entry_rsi": 25}, now=NOW)  # fmt: skip
    return conn, owner, cid


def run(
    conn,
    *,
    strategy="trend_pullback",
    params='{"entry_rsi": 25, "exit_rsi": 60}',
    cost='{"placeholder": false}',
    mode="strict",
):
    return conn.execute(
        "INSERT INTO backtest_run (strategy_id,strategy_version,params,params_hash,code_version,reader_mode,config,"
        "cost_model,adjustment_versions,provisional_events,unapplied_events,blocked_instruments,unmodelled_events,"
        "accounting_complete,dividends_received,metrics,result_hash,created_at,ledger_reconciled,reconciliation,pnl)"
        " VALUES (%s,'1',%s,'ph','c',%s,'{}',%s,'{}','[]','[]','[]','[]',true,0,'{}','rh',%s,true,'{}','{}') RETURNING run_id",
        (strategy, params, mode, cost, NOW),
    ).fetchone()[0]  # fmt: skip


def validated(conn, run_id, *, passed=True, status="confirmed"):
    exp = register(conn, name=f"e{run_id}", strategy_id="s", hypothesis="h", style="long_only", param_ranges={},
                   holdout=(NOW.date(), NOW.date()), now=NOW)  # fmt: skip
    ev = Evidence()
    rep = evaluate(ev, Thresholds(*([0.0] * 12)), status)
    rid = save_report(conn, exp, run_id, rep, ev, 1, NOW)
    conn.execute("UPDATE validation_report SET passed=%s WHERE report_id=%s", (passed, rid))


def test_a_new_strategy_is_in_research_and_can_enter_paper_under_the_waiver_which_is_recorded(env):
    conn, owner, cid = env
    assert stage.current(conn, cid) == "RESEARCH" and stage.history(conn, cid) == []
    stage.change(conn, cid, "PAPER", owner, NOW, reason="prove the plumbing")
    assert stage.current(conn, cid) == "PAPER"
    (h,) = stage.history(conn, cid)
    assert (h["from_stage"], h["to_stage"], h["reason"]) == (
        "RESEARCH",
        "PAPER",
        "prove the plumbing",
    )
    assert "unvalidated" in h["waived"][0] and h["approver"] == "Test User"


def test_live_is_refused_without_a_run_and_lists_every_blocker_of_a_weak_one(env):
    conn, owner, cid = env
    stage.change(conn, cid, "PAPER", owner, NOW, reason="r")
    with pytest.raises(stage.StageError, match="needs a backtest run"):
        stage.change(conn, cid, "LIVE", owner, NOW, reason="go")
    weak = run(conn, mode="research", cost='{"placeholder": true, "zero_slippage": true}')
    with pytest.raises(stage.StageError) as e:
        stage.change(conn, cid, "LIVE", owner, NOW, reason="go", run_id=weak)
    msg = str(e.value)
    assert (
        "strict reader mode" in msg and "placeholder cost model" in msg and "zero slippage" in msg
    )
    assert "validation protocol" in msg
    assert stage.current(conn, cid) == "PAPER"  # nothing changed


def test_live_needs_a_clean_validated_run_of_this_strategy_with_these_settings(env):
    conn, owner, cid = env
    stage.change(conn, cid, "PAPER", owner, NOW, reason="r")
    good = run(conn)
    with pytest.raises(stage.StageError, match="validation protocol"):
        stage.change(
            conn, cid, "LIVE", owner, NOW, reason="go", run_id=good
        )  # clean but never validated
    validated(conn, good, status="provisional")
    with pytest.raises(stage.StageError, match="validation protocol"):
        stage.change(
            conn, cid, "LIVE", owner, NOW, reason="go", run_id=good
        )  # validated against provisional thresholds
    other = run(conn, strategy="other")
    validated(conn, other)
    with pytest.raises(stage.StageError, match="different strategy"):
        stage.change(conn, cid, "LIVE", owner, NOW, reason="go", run_id=other)
    different = run(conn, params='{"entry_rsi": 30}')
    validated(conn, different)
    with pytest.raises(stage.StageError, match="different settings"):
        stage.change(conn, cid, "LIVE", owner, NOW, reason="go", run_id=different)
    ok = run(conn)
    validated(conn, ok)
    stage.change(conn, cid, "LIVE", owner, NOW, reason="validated and approved", run_id=ok)
    assert stage.current(conn, cid) == "LIVE" and stage.history(conn, cid)[-1]["run_id"] == ok


def test_the_only_ways_up_are_research_to_paper_to_live_and_going_down_is_always_allowed(env):
    conn, owner, cid = env
    with pytest.raises(stage.StageError, match="through paper"):
        stage.change(conn, cid, "LIVE", owner, NOW, reason="skip", run_id=run(conn))
    with pytest.raises(stage.StageError, match="already"):
        stage.change(conn, cid, "RESEARCH", owner, NOW, reason="same")
    stage.change(conn, cid, "PAPER", owner, NOW, reason="r")
    ok = run(conn)
    validated(conn, ok)
    stage.change(conn, cid, "LIVE", owner, NOW, reason="r", run_id=ok)
    stage.change(conn, cid, "PAPER", owner, NOW, reason="pulled back")  # no gate going down
    stage.change(conn, cid, "RESEARCH", owner, NOW, reason="rethink")
    assert [h["to_stage"] for h in stage.history(conn, cid)] == [
        "PAPER",
        "LIVE",
        "PAPER",
        "RESEARCH",
    ]


def test_a_reason_is_required_and_the_record_cannot_be_edited_or_removed(env):
    conn, owner, cid = env
    with pytest.raises(stage.StageError, match="reason"):
        stage.change(conn, cid, "PAPER", owner, NOW, reason="  ")
    stage.change(conn, cid, "PAPER", owner, NOW, reason="r")
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        conn.execute("UPDATE strategy_stage_change SET reason='x'")
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        conn.execute("DELETE FROM strategy_stage_change")


def test_deleting_a_strategy_takes_its_history_and_an_unknown_strategy_is_refused(env):
    conn, owner, cid = env
    stage.change(conn, cid, "PAPER", owner, NOW, reason="r")
    configs.delete(conn, owner, cid)
    assert conn.execute("SELECT count(*) FROM strategy_stage_change").fetchone() == (0,)
    with pytest.raises(stage.StageError, match="no such strategy"):
        stage.change(conn, cid, "PAPER", owner, NOW, reason="r")
