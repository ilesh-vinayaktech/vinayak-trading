"""Filed ratios in a backtest: the loader, and a fundamental screen run through the real engine. ENGINEERING_TEST_ONLY:
synthetic prices and filings, nothing here is a strategy result."""

from datetime import UTC, date, datetime, time
from decimal import Decimal as D

import pytest

from algo.research import fundamentals_book, study_jobs
from algo.research.study_runner import run_study
from tests.integration.test_study_runner import DAYS, NOW, build_env, registered
from tests.support.filings import add_filings

pytestmark = pytest.mark.integration
ENDS = [
    date(2023, 3, 31),
    date(2023, 6, 30),
    date(2023, 9, 30),
    date(2023, 12, 31),
    date(2024, 3, 31),
    date(2024, 6, 30),
]


@pytest.fixture
def env(conn):
    conn, owner = build_env(conn, DAYS)
    ids = dict(conn.execute("SELECT symbol, instrument_id FROM instrument").fetchall())
    for k in range(8):  # S{k} earns k+1 a quarter: the higher k, the cheaper it is
        add_filings(conn, ids[f"S{k}"], f"S{k}", f"INE00000000{k}", k + 1, ENDS, NOW)
    return conn, owner, list(ids.values())


def test_the_loader_keeps_nothing_filed_after_the_day_it_is_told_to_stop_at(env):
    conn, _, ids = env
    day = DAYS[-1]
    full = fundamentals_book.load(conn, ids, DAYS[0], day)
    assert full.ratios(ids[0], datetime.combine(day, time(12), UTC), D(100), day)["pe"] is not None
    cut = fundamentals_book.load(
        conn, ids, DAYS[0], date(2024, 2, 1)
    )  # the December quarter is filed in mid-February
    assert cut.ratios(ids[0], datetime.combine(day, time(12), UTC), D(100), day)["pe"] is None


def test_a_fundamental_screen_runs_through_the_real_engine_and_buys_the_cheap_stocks(env):
    conn, owner, _ = env
    screen = {
        "conditions": [{"field": "pe", "op": "lt", "value": 1000}],
        "sort": "pe",
        "descending": False,
    }
    sid = registered(
        conn, owner, strategy_id="screener", grid={"max_positions": [5]}, screen=screen
    )
    rid = study_jobs.enqueue(conn, sid, owner, NOW)
    run_study(conn, rid, NOW)
    run = study_jobs.get_run(conn, rid)
    assert (run["status"], run["error"]) == ("DONE", None)
    (t,) = study_jobs.trials(conn, sid)
    assert t["status"] == "DONE" and t["metrics"]["trades"] > 0
    bought = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT i.symbol FROM backtest_trade t JOIN instrument i USING (instrument_id) WHERE t.side='BUY'"
        )
    }
    assert bought == {
        "S3",
        "S4",
        "S5",
        "S6",
        "S7",
    }  # five slots, lowest P/E first (S0..S2 earn least)
