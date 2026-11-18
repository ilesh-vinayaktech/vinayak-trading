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
    assert forecast.tonight(conn, "night", NOW) > 0
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
    forecast.tonight(conn, "night", NOW)
    outcome, realized = conn.execute(
        "SELECT outcome_up, realized FROM prediction_log WHERE live AND as_of=%s AND horizon_days=1 AND subject='MARKET'",
        (DAYS[-2],),
    ).fetchone()
    assert outcome == bool(closes[-1] > closes[-2]) and realized == pytest.approx(
        closes[-1] / closes[-2] - 1, abs=1e-4
    )
    s = forecast.track_record(conn, "MARKET", 1, True, product="night")
    assert s is not None and s.n == 1
    assert (
        forecast.track_record(conn, "MARKET", 1, False) is None
    )  # no walk-forward history was written


def test_running_twice_gives_the_same_prediction_and_with_no_data_nothing_happens(env, closes):  # noqa: F811
    conn, _ = env
    assert forecast.tonight(conn, "night", NOW) == 0
    for i in range(len(DAYS)):
        put_day(conn, i, closes[i])
    forecast.tonight(conn, "night", NOW)
    a = conn.execute("SELECT p_up FROM prediction_log WHERE live ORDER BY horizon_days").fetchall()
    forecast.tonight(conn, "night", NOW)
    assert (
        conn.execute("SELECT p_up FROM prediction_log WHERE live ORDER BY horizon_days").fetchall()
        == a
    )


def put_us(conn, upto):
    """US closes for every day up to position `upto` (a gentle random walk), so the overnight figures exist."""
    rng = np.random.default_rng(9)
    for sym in ("SP500", "NASDAQ", "VIXUS"):
        px = 100.0
        for i in range(upto + 1):
            px *= 1 + rng.normal(0, 0.01)
            conn.execute(
                "INSERT INTO global_daily (symbol, day, close, source, ingested_at) VALUES (%s,%s,%s,'test',%s)",
                (sym, DAYS[i], px, NOW),
            )


def test_night_and_morning_are_separate_products_and_a_live_call_is_never_rewritten(env, closes):  # noqa: F811
    conn, _ = env
    for i in range(len(DAYS)):
        put_day(conn, i, closes[i])
    assert (
        forecast.tonight(conn, "morning", NOW) == 0
    )  # no US data in yet: no morning forecast, never a guess
    put_us(conn, len(DAYS) - 1)
    assert forecast.tonight(conn, "night", NOW) > 0 and forecast.tonight(conn, "morning", NOW) > 0
    got = {
        r[0]: r
        for r in conn.execute(
            "SELECT model_version, p_up, features, made_at, train_through FROM prediction_log WHERE live AND subject='MARKET' AND horizon_days=1"
        )
    }
    assert set(got) == {"logit-v2-night", "logit-v2-morning"}
    assert (
        "us_sp" not in got["logit-v2-night"][2] and "us_sp" in got["logit-v2-morning"][2]
    )  # the night forecast never sees the US session
    assert got["logit-v2-morning"][3] == NOW and got["logit-v2-morning"][4] < DAYS[-1]
    before = got["logit-v2-morning"][1]
    conn.execute("UPDATE global_daily SET close = close * 1.05 WHERE symbol='SP500'")
    forecast.tonight(conn, "morning", NOW)
    assert (
        conn.execute(
            "SELECT p_up FROM prediction_log WHERE live AND model_version='logit-v2-morning' AND subject='MARKET' AND horizon_days=1"
        ).fetchone()[0]
        == before
    )


def test_a_missing_figure_is_kept_as_missing_in_the_evidence_not_turned_into_a_number(env, closes):  # noqa: F811
    conn, _ = env
    for i in range(len(DAYS)):
        put_day(conn, i, closes[i])
    conn.execute(
        "UPDATE market_regime_daily SET components = components - 'breadth' WHERE day=%s",
        (DAYS[-1],),
    )
    forecast.tonight(conn, "night", NOW)
    feats = conn.execute(
        "SELECT features FROM prediction_log WHERE live AND subject='MARKET' AND horizon_days=1"
    ).fetchone()[0]
    assert feats["breadth"] is None and feats["momentum"] is not None


def test_the_frozen_candidate_is_logged_beside_production_on_the_same_inputs_as_its_own_market_only_version(
    env,  # noqa: F811
    closes,
):
    conn, _ = env
    for i in range(len(DAYS)):
        put_day(conn, i, closes[i])
    put_us(conn, len(DAYS) - 1)
    assert (
        forecast.tonight(conn, "morning", NOW) > 0 and forecast.tonight(conn, "morning7", NOW) > 0
    )
    rows = conn.execute(
        "SELECT model_version, subject, live, features FROM prediction_log WHERE model_version IN ('logit-v2-morning','logit-v2-morning7') AND live"
    ).fetchall()
    cand = [r for r in rows if r[0] == "logit-v2-morning7"]
    assert {r[1] for r in cand} == {"MARKET"} and all(
        r[2] for r in cand
    )  # a market model only, live only (no walk-forward history was written for it)
    assert set(cand[0][3]) == set(
        forecast.CANDIDATES["morning7"]
    )  # exactly the frozen seven features
    prod = next(r for r in rows if r[0] == "logit-v2-morning" and r[1] == "MARKET")
    assert {k: v for k, v in prod[3].items() if k in forecast.CANDIDATES["morning7"]} == cand[0][
        3
    ]  # the same values: same information cutoff
    assert (
        conn.execute(
            "SELECT count(*) FROM prediction_log WHERE model_version='logit-v2-morning7' AND NOT live"
        ).fetchone()[0]
        == 0
    )
    forecast.backfill(conn)
    assert (
        conn.execute(
            "SELECT count(*) FROM prediction_log WHERE model_version='logit-v2-morning7' AND NOT live"
        ).fetchone()[0]
        == 0
    )  # a backfill never writes the candidate
