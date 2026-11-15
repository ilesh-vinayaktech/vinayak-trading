# ruff: noqa: E501
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from algo.core.clock import SimClock
from algo.data.store.migrate import migrate
from algo.learning import health
from algo.paper import book
from tests.support.portal import add_user

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 10, tzinfo=UTC)
START = date(2026, 1, 5)
PAPER_FROM = START + timedelta(days=100)


def curve(first, returns):
    eq, out, d = D(1000), {first: D(1000)}, first
    for r in returns:
        d += timedelta(days=1)
        eq = eq * D(str(1 + r))
        out[d] = eq
    return out


def seed(conn, live_returns):
    migrate(conn)
    uid = add_user(conn, SimClock(NOW), "TRADER", "t@example.com")
    book.create_account(
        conn,
        uid,
        strategy_id="trend_pullback",
        params={"trend_sma": 200, "entry_rsi": 25, "exit_rsi": 60, "max_positions": 10},
        initial_cash=D(1_000_000),
        started_on=PAPER_FROM,
        now=NOW,
    )
    run_id = conn.execute(
        "INSERT INTO backtest_run (strategy_id,strategy_version,params,params_hash,code_version,reader_mode,config,cost_model,adjustment_versions,provisional_events,unapplied_events,blocked_instruments,unmodelled_events,accounting_complete,dividends_received,metrics,result_hash,created_at)"
        " VALUES ('trend_pullback','1','{}','h','c','research','{}','{}','{}','[]','[]','{}','[]',true,0,'{}','x',%s) RETURNING run_id", (NOW,)).fetchone()[0]  # fmt: skip
    # the backtest covers 200 days, the paper account starts on day 100 (so only the first 100 days are 'development')
    for d, v in curve(START, [0.01, -0.008] * 100).items():
        conn.execute(
            "INSERT INTO backtest_equity (run_id, day, equity) VALUES (%s,%s,%s)", (run_id, d, v)
        )
    for d, v in curve(PAPER_FROM, live_returns).items():
        conn.execute(
            "INSERT INTO paper_equity (user_id, day, equity, cash) VALUES (%s,%s,%s,0)", (uid, d, v)
        )
    return uid, run_id


def recorded(conn):
    return conn.execute(
        "SELECT check_name, status, detail FROM dq_result WHERE check_name='degradation'"
    ).fetchall()


def test_a_paper_account_behaving_like_its_backtest_is_ok_and_recorded_as_a_pass(conn):
    uid, run_id = seed(conn, [0.01, -0.008] * 20)
    h = health.check(conn, uid, run_id, now=NOW)
    assert h.status == "OK" and h.evidence["ref_days"] == 99  # only days before the first paper day
    assert [(r[0], r[1]) for r in recorded(conn)] == [("degradation", "PASS")] and "z=" in recorded(
        conn
    )[0][2]


def test_a_paper_account_losing_money_the_backtest_never_did_is_degraded_and_recorded_as_a_failure(
    conn,
):
    uid, run_id = seed(conn, [-0.015, 0.005] * 20)
    h = health.check(conn, uid, run_id, now=NOW)
    assert h.status == "DEGRADED"
    (name, status, detail) = recorded(conn)[0]
    assert status == "FAIL" and detail.startswith("DEGRADED: mean return")


def test_too_little_paper_history_is_insufficient_and_says_so_in_the_record(conn):
    uid, run_id = seed(conn, [0.01, -0.008] * 5)
    assert health.check(conn, uid, run_id, now=NOW).status == "INSUFFICIENT"
    assert recorded(conn)[0][1] == "PASS" and recorded(conn)[0][2].startswith("INSUFFICIENT: only")


def test_an_account_with_no_paper_days_yet_is_insufficient(conn):
    migrate(conn)
    uid = add_user(conn, SimClock(NOW), "TRADER", "t@example.com")
    run_id = conn.execute(
        "INSERT INTO backtest_run (strategy_id,strategy_version,params,params_hash,code_version,reader_mode,config,cost_model,adjustment_versions,provisional_events,unapplied_events,blocked_instruments,unmodelled_events,accounting_complete,dividends_received,metrics,result_hash,created_at)"
        " VALUES ('trend_pullback','1','{}','h','c','research','{}','{}','{}','[]','[]','{}','[]',true,0,'{}','x',%s) RETURNING run_id", (NOW,)).fetchone()[0]  # fmt: skip
    assert health.check(conn, uid, run_id, now=NOW).status == "INSUFFICIENT"
    assert recorded(conn)[0][1] == "PASS" and recorded(conn)[0][2].startswith("INSUFFICIENT:")
