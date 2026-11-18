# ruff: noqa: E501
"""The live-data checks: each rule fires on the case it names and is silent otherwise, and none of the market-hours rules fires unless the equity feed is itself live."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest

from algo.data.store.migrate import migrate
from algo.jobs.data_checks import problems
from algo.live.bar_store import save_status
from algo.live.index_store import TRACKED

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 18, 6, 0, tzinfo=UTC)  # 11:30 IST on a Wednesday


@pytest.fixture
def db(conn):
    migrate(conn)
    return conn


def feed(conn, state="CONNECTED", ticked=NOW):
    save_status(
        conn,
        state,
        "x",
        subscribed=1,
        last_tick_at=ticked,
        last_bar_at=None,
        ticks=1,
        bars=0,
        bad_frames=0,
        late_ticks=0,
        now=NOW,
    )


def quote_all(conn, when=NOW, n=None):
    for k, (ex, sym) in enumerate(TRACKED[: n or len(TRACKED)]):
        conn.execute(
            "INSERT INTO index_live_quote (token, exchange, symbol, ltp, updated_at) VALUES (%s,%s,%s,1,%s)",
            (k + 1, ex, sym, when),
        )


NO_LAKE = Path("/nonexistent/lake")  # no constituent lists captured: the list rule stays quiet


def texts(conn, now=NOW, lake=NO_LAKE):
    return [p.text for p in problems(conn, now, lake)]


def test_a_quiet_database_has_no_problems_and_no_market_rule_fires_without_a_live_feed(db):
    assert texts(db) == []
    quote_all(db, when=NOW - timedelta(hours=3), n=2)  # stale, but nothing says the feed is running
    assert texts(db) == []
    feed(db, state="STOPPED")
    assert texts(db) == []


def test_index_quotes_must_be_fresh_and_nearly_all_present_while_the_feed_is_live(db):
    feed(db)
    quote_all(db)
    assert texts(db) == []
    db.execute("DELETE FROM index_live_quote")
    quote_all(db, n=3)
    assert any("Only 3 of" in t for t in texts(db))  # three indices quoted of all followed
    db.execute("DELETE FROM index_live_quote")
    quote_all(db, when=NOW - timedelta(minutes=10))
    assert any("Only 0 of" in t for t in texts(db))  # all quotes ten minutes old count as none


def test_index_minute_bars_must_keep_coming_while_the_feed_is_live(db):
    feed(db)
    quote_all(db)
    db.execute(
        "INSERT INTO index_bar_1m (token, exchange, symbol, ts, open, high, low, close, source, built_at) VALUES (1,'NSE','NIFTY 50',%s,1,1,1,1,'live',%s)",
        (NOW - timedelta(minutes=2), NOW),
    )
    assert texts(db) == []
    db.execute("UPDATE index_bar_1m SET ts = %s", (NOW - timedelta(minutes=20),))
    assert any("newest index minute bar is 20 min old" in t for t in texts(db))


def put_news(conn, item_id, published, first_seen, laya=None):
    conn.execute(
        "INSERT INTO news_item (item_id, source, title, summary, url, published_at, first_seen_at, hits, symbols, laya_sentiment) VALUES (%s,'feed','t','',%s,%s,%s,0,'{}',%s)",
        (item_id, f"https://ex.com/{item_id}", published, first_seen, laya),
    )


def test_no_headline_for_eight_hours_is_a_problem_and_no_news_at_all_is_not(db):
    assert texts(db) == []  # never ran: the job-never-ran check owns that
    put_news(db, "a", NOW - timedelta(hours=3), NOW - timedelta(hours=3), laya=0.1)
    assert texts(db) == []
    db.execute("UPDATE news_item SET published_at = %s", (NOW - timedelta(hours=9),))
    assert any("No new headline for 9 h" in t for t in texts(db))


def test_headlines_that_wait_for_the_laya_model_are_counted_after_half_an_hour(db):
    put_news(
        db, "fresh", NOW - timedelta(minutes=10), NOW - timedelta(minutes=10)
    )  # not yet: the next run will take it
    assert texts(db) == []
    put_news(db, "late", NOW - timedelta(hours=2), NOW - timedelta(hours=2))
    put_news(db, "late2", NOW - timedelta(hours=3), NOW - timedelta(hours=3))
    assert any("2 headlines have waited over 30 min for the Laya model" in t for t in texts(db))
    put_news(
        db, "old", NOW - timedelta(days=3), NOW - timedelta(days=3)
    )  # more than a day old and never scored: given up, not an alarm
    assert any("2 headlines" in t for t in texts(db))


def test_the_live_zone_needs_a_baseline_for_the_last_trading_day_from_half_past_eight(db):
    from algo.data.store.instruments import InstrumentRepo
    from tests.support.bt import put_bars

    repo = InstrumentRepo(db)
    iid = repo.add_instrument(repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE"), "AAA")
    put_bars(db, iid, {date(2026, 11, 17): D(100)})
    assert any("no baseline for the last trading day (2026-11-17)" in t for t in texts(db))
    db.execute(
        "INSERT INTO breadth_baseline VALUES (%s,%s,1,0,0,0,0,0,1,1,0,0,%s)",
        (date(2026, 11, 17), iid, NOW),
    )
    assert texts(db) == []
    early = datetime(2026, 11, 18, 2, 0, tzinfo=UTC)  # 07:30 IST: too early to expect one
    db.execute("DELETE FROM breadth_baseline")
    assert texts(db, now=early) == []
    sunday = datetime(2026, 11, 22, 6, 0, tzinfo=UTC)
    assert texts(db, now=sunday) == []  # not a trading day


def test_stale_constituent_lists_are_reported_after_two_weeks(db, tmp_path):
    folder = tmp_path / "raw/niftyindices/nifty50_list"
    (folder / "dt=2026-11-10").mkdir(parents=True)
    assert texts(db, lake=tmp_path) == []
    (folder / "dt=2026-11-10").rename(folder / "dt=2026-10-01")
    assert any("constituent lists are 48 days old" in t for t in texts(db, lake=tmp_path))
