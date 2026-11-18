# ruff: noqa: E501, F811
"""The live market zone: today's breadth from live prices must equal what the finished-day query says for the same prices, and the zone must fall back to nothing
(so the snapshot stays) whenever a piece is missing."""

from datetime import UTC, date, datetime, time, timedelta

import pytest

from algo.live.market_calendar import IST
from algo.market.breadth import daily_breadth
from algo.market.build import refresh_breadth, score
from algo.market.live_zone import live_breadth, live_zone, refresh_baseline
from tests.integration.market.test_breadth import DAYS, env  # noqa: F401  (env is a fixture)
from tests.integration.market.test_build import NOW, full  # noqa: F401  (full is a fixture)

pytestmark = pytest.mark.integration
TODAY = DAYS[-1]
OPEN_IST = datetime.combine(TODAY, time(10, 30), IST).astimezone(UTC)


def quote_from_last_bar(conn, when=OPEN_IST):
    """Make today's last stored bar look like a live quote (price = close, volume = the day's), then drop the bar so only history before today remains."""
    rows = conn.execute(
        "SELECT instrument_id, close, volume FROM bar_1d WHERE (ts AT TIME ZONE 'Asia/Kolkata')::date = %s",
        (TODAY,),
    ).fetchall()
    for iid, close, volume in rows:
        conn.execute(
            "INSERT INTO live_quote (instrument_id, ltp, volume, updated_at) VALUES (%s,%s,%s,%s)",
            (iid, close, volume, when),
        )
    conn.execute("DELETE FROM bar_1d WHERE (ts AT TIME ZONE 'Asia/Kolkata')::date = %s", (TODAY,))
    return len(rows)


def test_live_breadth_counts_exactly_what_the_finished_day_query_counts(env):  # noqa: F811
    conn, _ = env
    finished = daily_breadth(conn, TODAY, TODAY)[0]
    quote_from_last_bar(conn)
    assert refresh_baseline(conn, TODAY, OPEN_IST) > 0
    live = live_breadth(conn, TODAY)
    assert live == finished  # the same stocks, the same averages, the same highs and lows


def test_without_a_baseline_for_the_last_trading_day_or_without_enough_quotes_there_is_no_live_reading(
    env,
):  # noqa: F811
    conn, ids = env
    quote_from_last_bar(conn)
    assert live_breadth(conn, TODAY) is None  # no baseline stored yet
    refresh_baseline(conn, TODAY, OPEN_IST)
    assert live_breadth(conn, TODAY) is not None
    conn.execute("DELETE FROM live_quote WHERE instrument_id <> %s", (ids["A"],))
    assert live_breadth(conn, TODAY) is None  # one stock of five quoted: the feed is not really on
    assert (
        live_breadth(conn, TODAY - timedelta(days=30)) is None
    )  # a baseline for another day does not apply


def test_a_quote_from_an_earlier_day_does_not_count_as_live(env):  # noqa: F811
    conn, _ = env
    quote_from_last_bar(conn, when=OPEN_IST - timedelta(days=1))
    refresh_baseline(conn, TODAY, OPEN_IST)
    assert live_breadth(conn, TODAY) is None


def test_the_live_zone_scores_today_against_the_stored_history_and_follows_the_live_index(full):  # noqa: F811
    conn = full
    refresh_breadth(conn, DAYS[0], NOW)
    score(conn, DAYS[0], NOW)
    conn.execute(
        "DELETE FROM market_regime_daily WHERE day = %s", (TODAY,)
    )  # the nightly job has not run for today yet
    quote_from_last_bar(conn)
    refresh_baseline(conn, TODAY, OPEN_IST)
    calm = live_zone(conn, TODAY)
    assert (
        calm is not None
        and calm.fear_greed is not None
        and calm.history[-1][0] == TODAY
        and len(calm.history) > 50
    )
    assert calm.label is not None and calm.breadth.universe == 4
    for token, sym, level in (
        (1, "INDIA VIX", 80.0),
        (2, "NIFTY 500", 500.0),
    ):  # a panic: fear index spikes, the market index drops
        conn.execute(
            "INSERT INTO index_live_quote (token, exchange, symbol, ltp, updated_at) VALUES (%s,'NSE',%s,%s,%s)",
            (token, sym, level, OPEN_IST),
        )
    panic = live_zone(conn, TODAY)
    assert panic is not None and panic.fear_greed is not None and panic.fear_greed < calm.fear_greed


def test_no_stored_history_means_no_live_zone(env):  # noqa: F811
    conn, _ = env
    quote_from_last_bar(conn)
    refresh_baseline(conn, TODAY, OPEN_IST)
    assert live_zone(conn, TODAY) is None


def test_the_baseline_keeps_one_generation_only(env):  # noqa: F811
    conn, _ = env
    refresh_baseline(conn, TODAY, OPEN_IST)
    refresh_baseline(conn, TODAY + timedelta(days=3), OPEN_IST)
    assert conn.execute("SELECT count(DISTINCT last_bar) FROM breadth_baseline").fetchone() == (1,)
    assert (
        refresh_baseline(conn, date(2000, 1, 1), OPEN_IST) == 0
    )  # no earlier bars at all: nothing stored
