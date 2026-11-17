# ruff: noqa: E501
"""The market zone route: the latest day with its breadth, the signals ranked greediest first, a year of history oldest first; nothing yet is an empty answer, and
only signed-in people can read it."""

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from tests.integration.portal.test_paper_routes import env, trader  # noqa: F401  (env is a fixture)
from tests.support.portal import add_user, sign_in

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)
TODAY = date(2026, 11, 11)


def put(conn, day, fg, label, trend, comps=None):
    conn.execute(
        "INSERT INTO market_regime_daily (day, universe, advancers, decliners, unchanged, n50, above50, n200, above200, highs, lows, fear_greed, label, trend, volatility, components, computed_at)"
        " VALUES (%s,1600,900,600,100,1500,600,1400,800,45,12,%s,%s,%s,'NORMAL',%s,%s)",
        (day, fg, label, trend, Jsonb(comps) if comps else None, NOW),
    )


def test_nothing_built_yet_is_an_empty_answer(env):  # noqa: F811
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    assert c.get("/api/market/zone").json() == {"latest": None, "history": [], "drivers": []}


def test_the_latest_day_its_breadth_and_the_signals_ranked_greediest_first(env):  # noqa: F811
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    put(conn, TODAY - timedelta(days=2), 41.0, "Fear", "SIDEWAYS")
    put(conn, TODAY - timedelta(days=1), 52.0, "Neutral", "SIDEWAYS")
    comps = {"momentum": 80.5, "breadth": 20.0, "volatility": 55.0, "stocks_vs_bonds": None}
    put(conn, TODAY, 63.5, "Greed", "BULL", comps)
    got = c.get("/api/market/zone").json()
    assert got["latest"] == {
        "day": "2026-11-11", "age_days": 0, "fear_greed": 63.5, "label": "Greed", "trend": "BULL", "volatility": "NORMAL",
        "universe": 1600, "advancers": 900, "decliners": 600, "unchanged": 100, "pct_above_50": 40.0, "pct_above_200": 57.1,
        "highs": 45, "lows": 12,
    }  # fmt: skip
    assert [d["key"] for d in got["drivers"]] == [
        "momentum",
        "volatility",
        "breadth",
    ]  # the unscored one is left out
    assert got["drivers"][0] == {
        "key": "momentum",
        "name": "Index trend against its 125-day average",
        "score": 80.5,
    }
    assert [h["day"] for h in got["history"]] == [
        "2026-11-09",
        "2026-11-10",
        "2026-11-11",
    ]  # oldest first


def test_a_stale_row_says_how_old_it_is_and_unscored_days_stay_out_of_the_history(env):  # noqa: F811
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    put(conn, TODAY - timedelta(days=5), 70.0, "Greed", "BULL")
    put(conn, TODAY - timedelta(days=4), None, None, "UNKNOWN")
    got = c.get("/api/market/zone").json()
    assert got["latest"]["age_days"] == 4 and got["latest"]["fear_greed"] is None
    assert [h["day"] for h in got["history"]] == ["2026-11-06"]


def test_only_signed_in_people_can_read_it(env):  # noqa: F811
    conn, app, clock, _ = env
    add_user(conn, clock, "VIEWER", "viewer@example.com")
    assert sign_in(app, "viewer@example.com").get("/api/market/zone").status_code == 200
    assert TestClient(app).get("/api/market/zone").status_code == 401
