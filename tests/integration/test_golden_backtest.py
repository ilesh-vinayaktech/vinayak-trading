# ruff: noqa: E501
"""A golden backtest: one fixed synthetic world through the engine, its result pinned in tests/data/golden_backtest.json. Any change to the engine,
the strategy, the costs or the adjustment that moves a trade or an equity point fails here; if the change is intended, regenerate with
UPDATE_GOLDEN=1 and review the diff of the file in the same commit. ENGINEERING_TEST_ONLY: synthetic prices."""

import json
import os
from pathlib import Path

import pytest

from tests.integration.test_trend_pullback_engine import go, market  # noqa: F401

pytestmark = pytest.mark.integration
GOLDEN = Path(__file__).parents[1] / "data/golden_backtest.json"


def test_the_engine_reproduces_the_stored_golden_result(market):  # noqa: F811
    conn, ids = market
    _, result = go(conn, ids)
    got = {
        "strategy": [result.strategy_id, result.strategy_version],
        "result_hash": result.result_hash,
        "trades": len(result.trades),
        "first_trade": [
            str(result.trades[0].day),
            result.trades[0].side,
            str(result.trades[0].qty),
            str(result.trades[0].price),
        ],
        "equity_days": len(result.equity),
        "final_equity": str(result.equity[-1][1]),
    }
    assert got["trades"] > 0, "the scenario must trade or the golden file pins nothing"
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n")
    assert json.loads(GOLDEN.read_text()) == got, (
        "the backtest result changed: if intended, run with UPDATE_GOLDEN=1 and review tests/data/golden_backtest.json"
    )


def test_a_second_run_in_the_same_process_gives_the_identical_hash(market):  # noqa: F811
    conn, ids = market
    assert go(conn, ids)[1].result_hash == go(conn, ids)[1].result_hash
