# ruff: noqa: E501
import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal as D
from pathlib import Path

import pytest

from algo.core.clock import SimClock
from algo.data.store.migrate import migrate
from algo.paper import book
from tests.support.portal import add_user

pytestmark = pytest.mark.integration
ROOT = Path(__file__).parents[3]
NOW = datetime(2026, 11, 10, tzinfo=UTC)
DAYS = [date(2026, 11, d) for d in (2, 3, 4, 5, 6)]


def run(pg_url, uid, run_id, *extra):
    return subprocess.run([sys.executable, str(ROOT / "scripts/paper_tracking.py"), "--db", pg_url, "--user", str(uid), "--run", str(run_id), *extra],
                          capture_output=True, text=True, cwd=ROOT, env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"})  # fmt: skip


def seed(conn, live, model):
    migrate(conn)
    uid = add_user(conn, SimClock(NOW), "TRADER", "t@example.com")
    book.create_account(
        conn,
        uid,
        strategy_id="trend_pullback",
        params={"trend_sma": 200, "entry_rsi": 25, "exit_rsi": 60, "max_positions": 10},
        initial_cash=D(1_000_000),
        started_on=DAYS[0],
        now=NOW,
    )
    run_id = conn.execute(
        "INSERT INTO backtest_run (strategy_id,strategy_version,params,params_hash,code_version,reader_mode,config,cost_model,adjustment_versions,provisional_events,unapplied_events,blocked_instruments,unmodelled_events,accounting_complete,dividends_received,metrics,result_hash,created_at)"
        " VALUES ('trend_pullback','1','{}','h','c','research','{}','{}','{}','[]','[]','{}','[]',true,0,'{}','x',%s) RETURNING run_id", (NOW,)).fetchone()[0]  # fmt: skip
    for d, v in zip(DAYS, live, strict=True):
        conn.execute(
            "INSERT INTO paper_equity (user_id, day, equity, cash) VALUES (%s,%s,%s,0)", (uid, d, v)
        )
    for d, v in zip(DAYS, model, strict=True):
        conn.execute(
            "INSERT INTO backtest_equity (run_id, day, equity) VALUES (%s,%s,%s)", (run_id, d, v)
        )
    conn.commit()
    return uid, run_id


def test_a_paper_account_tracking_its_backtest_passes_and_a_diverging_one_fails_and_can_be_recorded(
    conn, pg_url
):
    uid, run_id = seed(conn, live=[100, 101, 102, 103, 104], model=[100, 101, 102, 103, 104])
    ok = run(pg_url, uid, run_id)
    assert ok.returncode == 0 and "tracking error 0.0" in ok.stdout, ok.stdout + ok.stderr
    conn.execute("DELETE FROM paper_equity")
    for d, v in zip(DAYS, [100, 103, 99, 108, 95], strict=True):
        conn.execute(
            "INSERT INTO paper_equity (user_id, day, equity, cash) VALUES (%s,%s,%s,0)", (uid, d, v)
        )
    conn.commit()
    bad = run(pg_url, uid, run_id, "--max-te", "0.05", "--record")
    assert bad.returncode == 1 and "allowed 0.05" in bad.stdout, bad.stdout + bad.stderr
    assert conn.execute("SELECT check_name, status FROM dq_result").fetchall() == [
        ("tracking", "FAIL")
    ]


def test_nothing_to_compare_is_an_error_not_a_pass(conn, pg_url):
    uid, run_id = seed(conn, live=[100, 101, 102, 103, 104], model=[100, 101, 102, 103, 104])
    r = run(pg_url, uid, run_id + 99)
    assert r.returncode != 0 and "nothing to compare" in r.stderr + r.stdout
