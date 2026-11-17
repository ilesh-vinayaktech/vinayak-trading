# ruff: noqa: E501
"""The nightly forecast: a live prediction for the latest day with its evidence, and a later run resolves it from the index close and scores it."""

from datetime import UTC, datetime
from decimal import Decimal as D

import numpy as np
import pytest
from psycopg.types.json import Jsonb

from algo.market import forecast
from tests.integration.market.test_breadth import DAYS, env  # noqa: F401  (env is a fixture)

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 14, 4, 0, tzinfo=UTC)


def put_day(conn, i, close):
    d = DAYS[i]
    conn.execute(
        "INSERT INTO index_bar_1d (exchange, symbol, trade_date, open, high, low, close, token, ingested_at) VALUES ('NSE','NIFTY 500',%s,1,1,1,%s,1,%s)",
        (d, D(str(round(close, 4))), NOW),
    )
    conn.execute(
        "INSERT INTO market_regime_daily (day, universe, advancers, decliners, unchanged, n50, above50, n200, above200, highs, lows, fear_greed, label, trend, volatility, components, computed_at)"
        " VALUES (%s,100,%s,%s,0,100,50,100,50,5,5,%s,'Neutral','SIDEWAYS','NORMAL',%s,%s)",
        (
            d,
            40 + i % 30,
            60 - i % 30,
            40 + i % 25,
            Jsonb({"momentum": 30 + i % 40, "breadth": 50.0}),
            NOW,
        ),
    )


@pytest.fixture
def closes():
    return 1000 * np.cumprod(1 + np.random.default_rng(5).normal(0, 0.01, len(DAYS)))


def test_a_live_prediction_is_made_with_evidence_then_resolved_and_scored_the_next_run(env, closes):  # noqa: F811
    conn, _ = env
    for i in range(len(DAYS) - 1):
        put_day(conn, i, closes[i])
    assert forecast.tonight(conn) > 0
    rows = conn.execute(
        "SELECT as_of, subject, horizon_days, p_up, evidence, outcome_up FROM prediction_log WHERE live ORDER BY horizon_days"
    ).fetchall()
    assert {r[1] for r in rows} == {"MARKET"} and {r[2] for r in rows} == {1, 5}
    one = next(r for r in rows if r[2] == 1)
    assert (
        one[0] == DAYS[-2]
        and 0 < one[3] < 1
        and one[4]
        and {"feature", "value", "effect"} <= set(one[4][0])
        and one[5] is None
    )
    put_day(conn, len(DAYS) - 1, closes[-1])  # the next day arrives
    forecast.tonight(conn)
    outcome, realized = conn.execute(
        "SELECT outcome_up, realized FROM prediction_log WHERE live AND as_of=%s AND horizon_days=1 AND subject='MARKET'",
        (DAYS[-2],),
    ).fetchone()
    assert outcome == bool(closes[-1] > closes[-2]) and realized == pytest.approx(
        closes[-1] / closes[-2] - 1, abs=1e-4
    )
    s = forecast.track_record(conn, "MARKET", 1, True)
    assert s is not None and s.n == 1
    assert (
        forecast.track_record(conn, "MARKET", 1, False) is None
    )  # no walk-forward history was written


def test_running_twice_gives_the_same_prediction_and_with_no_data_nothing_happens(env, closes):  # noqa: F811
    conn, _ = env
    assert forecast.tonight(conn) == 0
    for i in range(len(DAYS)):
        put_day(conn, i, closes[i])
    forecast.tonight(conn)
    a = conn.execute("SELECT p_up FROM prediction_log WHERE live ORDER BY horizon_days").fetchall()
    forecast.tonight(conn)
    assert (
        conn.execute("SELECT p_up FROM prediction_log WHERE live ORDER BY horizon_days").fetchall()
        == a
    )
