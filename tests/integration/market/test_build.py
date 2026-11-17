# ruff: noqa: E501
"""Building the market zone table from stored breadth and the index series: one row per day, scored once there is history, idempotent, and a later run does not
change earlier days."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from algo.market.build import refresh, refresh_breadth, score
from tests.integration.market.test_breadth import DAYS, env  # noqa: F401  (env is a fixture)

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 14, 4, 0, tzinfo=UTC)


def put_index(conn, symbol, fn):
    for i, d in enumerate(DAYS):
        conn.execute(
            "INSERT INTO index_bar_1d (exchange, symbol, trade_date, open, high, low, close, token, ingested_at) VALUES ('NSE',%s,%s,1,1,1,%s,1,%s)",
            (symbol, d, D(str(round(fn(i), 4))), NOW),
        )


@pytest.fixture
def full(env):  # noqa: F811
    conn, _ = env
    put_index(conn, "NIFTY 500", lambda i: 1000 * 1.001**i)
    put_index(conn, "INDIA VIX", lambda i: 18 + (i % 9) * 0.3 - i * 0.01)
    put_index(conn, "NIFTY GS 10YR", lambda i: 2000 * 1.0002**i)
    return conn


def rows(conn):
    return conn.execute(
        "SELECT day, fear_greed, label, trend, volatility, components FROM market_regime_daily ORDER BY day"
    ).fetchall()


def test_every_day_with_liquid_stocks_gets_a_row_and_the_late_days_are_scored(full):
    conn = full
    stored, scored = refresh(conn, DAYS[0], NOW)
    out = rows(conn)
    assert stored == len(DAYS) and len(out) == len(DAYS) and scored > 0
    assert out[0][1] is None  # no history yet: no score, never a guess
    day, fg, label, trend, vol, comps = out[-1]
    assert 0 <= fg <= 100 and label in ("Extreme fear", "Fear", "Neutral", "Greed", "Extreme greed")
    assert trend in ("BULL", "BEAR", "SIDEWAYS") and vol in ("CALM", "NORMAL", "STRESSED")
    assert {"momentum", "breadth", "volatility", "stocks_vs_bonds"} <= set(comps)
    assert (
        comps["risk_appetite"] is None
    )  # those indices are not in this test: left out, not guessed


def test_running_again_changes_nothing_and_a_later_start_leaves_earlier_days_alone(full):
    conn = full
    refresh(conn, DAYS[0], NOW)
    before = rows(conn)
    refresh(conn, DAYS[0], NOW + timedelta(hours=1))
    assert rows(conn) == before
    refresh_breadth(conn, DAYS[-3], NOW + timedelta(hours=2))
    score(conn, DAYS[-3], NOW + timedelta(hours=2))
    assert rows(conn) == before


def test_with_no_breadth_stored_nothing_is_scored(env):  # noqa: F811
    conn, _ = env
    assert score(conn, DAYS[0], NOW) == 0
