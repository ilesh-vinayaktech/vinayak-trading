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
    db.execute("DELETE FROM breadth_baseline")
    db.execute(  # the evening market-zone job stamps the next session's baseline with the day it just loaded: newer is fine
        "INSERT INTO breadth_baseline VALUES (%s,%s,1,0,0,0,0,0,1,1,0,0,%s)",
        (date(2026, 11, 18), iid, NOW),
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


def overnight(conn, *, us_day=date(2026, 11, 17), vix_day=date(2026, 11, 17), gift=True):
    """The overnight inputs as the morning jobs leave them: US closes, GIFT Nifty's 08:45 reading."""
    for sym, day in (("SP500", us_day), ("VIXUS", vix_day)):
        conn.execute(
            "INSERT INTO global_daily (symbol, day, close, source, ingested_at) VALUES (%s,%s,100,'t',%s)",
            (sym, day, NOW),
        )
    if gift:
        conn.execute(
            "INSERT INTO global_daily (symbol, day, close, source, ingested_at) VALUES ('GIFT0845',%s,25000,'kite',%s)",
            (date(2026, 11, 18), NOW),
        )


def forecasts(conn, made=NOW, direction=("morning", "morning7"), range_made=True):
    for product in direction:
        conn.execute(
            "INSERT INTO prediction_log (as_of, subject, horizon_days, model_version, live, p_up, made_at) VALUES (%s,'MARKET',1,%s,true,0.55,%s)",
            (date(2026, 11, 17), f"logit-v2-{product}", made),
        )
    if range_made:
        conn.execute(
            "INSERT INTO range_forecast_log (as_of, model_version, made_at, forecast_range, features, train_through, n_train) VALUES (%s,'range-ridge-v1',%s,1.1,'{}',%s,600)",
            (date(2026, 11, 17), made, date(2026, 11, 17)),
        )


def said(conn, now):
    return [p.text for p in problems(conn, now, NO_LAKE)]


def test_the_overnight_rules_stay_quiet_until_the_overnight_data_has_ever_been_loaded(db):
    assert (
        said(db, NOW) == []
    )  # a database that never ran the morning jobs: nothing to say (a job that never ran is the job check's business)


def test_a_trading_morning_with_the_inputs_in_but_no_forecast_made_names_each_missing_forecast(db):
    overnight(db)
    got = said(db, NOW)
    assert len(got) == 3
    assert (
        any("morning direction forecast" in t for t in got)
        and any("morning7 direction forecast" in t for t in got)
        and any("expected-range forecast" in t for t in got)
    )
    forecasts(db)
    assert said(db, NOW) == []  # everything in and made: silent


def test_a_missing_us_close_or_gift_reading_is_named_with_the_session_it_should_have_been_for(db):
    overnight(db, vix_day=date(2026, 11, 16), gift=False)
    forecasts(db)
    got = said(db, NOW)
    assert len(got) == 2
    assert any("US VIX close for the US session of 2026-11-17" in t for t in got) and any(
        "GIFT Nifty's 08:45 reading for 2026-11-18" in t for t in got
    )


def test_each_rule_waits_for_the_time_its_job_should_have_run(db):
    overnight(db, gift=False)
    early = datetime(2026, 11, 18, 3, 10, tzinfo=UTC)  # 08:40 IST: before the morning jobs
    assert said(db, early) == []
    after_loads = datetime(
        2026, 11, 18, 3, 25, tzinfo=UTC
    )  # 08:55 IST: the loads are due, the forecasts are not yet
    got = said(db, after_loads)
    assert len(got) == 1 and "GIFT Nifty" in got[0]


def test_nothing_is_reported_on_a_day_the_market_is_closed(db):
    overnight(db, us_day=date(2026, 11, 10), vix_day=date(2026, 11, 10), gift=False)
    saturday = datetime(2026, 11, 21, 4, 0, tzinfo=UTC)
    assert said(db, saturday) == []


def test_fii_open_interest_a_day_behind_is_reported_only_after_the_evening_poll_window(db):
    overnight(db)
    forecasts(db)
    db.execute(
        "INSERT INTO fii_index_futures_oi (day, long_oi, short_oi, ingested_at) VALUES (%s,100,80,%s)",
        (date(2026, 11, 17), NOW),
    )
    assert said(db, NOW) == []  # 11:30 IST: today's file is not expected yet
    evening = datetime(2026, 11, 18, 16, 30, tzinfo=UTC)  # 22:00 IST
    got = said(db, evening)
    assert len(got) == 1 and "FII index-futures open interest for 2026-11-18 is not in" in got[0]
    db.execute(
        "INSERT INTO fii_index_futures_oi (day, long_oi, short_oi, ingested_at) VALUES (%s,100,80,%s)",
        (date(2026, 11, 18), NOW),
    )
    assert said(db, evening) == []


def test_rise_odds_a_day_behind_are_reported_after_the_evening_jobs_and_never_before_they_have_ever_run(
    db,
):
    evening = datetime(2026, 11, 18, 17, 30, tzinfo=UTC)  # 23:00 IST on a Wednesday
    early = datetime(
        2026, 11, 18, 14, 0, tzinfo=UTC
    )  # 19:30 IST: the market-zone job has not run yet
    from algo.data.store.instruments import InstrumentRepo

    x = InstrumentRepo(db).add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    iid = InstrumentRepo(db).add_instrument(x, "AAA")
    for d in (date(2026, 11, 17), date(2026, 11, 18)):
        db.execute(
            "INSERT INTO bar_1d (instrument_id, ts, open, high, low, close, volume, series, source, dataset_version, ingested_at) VALUES (%s, %s::date + time '03:45', 1,1,1,1,1,'EQ','nse',1, now())",
            (iid, d),
        )
    assert not any(
        "rise odds" in t for t in texts(db, evening)
    )  # never scored: the feature is not in use, so no alarm
    db.execute(
        "INSERT INTO rise_odds_model (version, horizon, train_end, trained_at, n_rows, features, payload, sha256) VALUES ('h5-2026-01-01', 5, '2026-01-01', now(), 1, %s, %s, 'x')",
        (["a"], b"x"),
    )
    db.execute(
        "INSERT INTO rise_odds (day, instrument_id, horizon, prob, pct, model_version) VALUES ('2026-11-17', %s, 5, 0.5, 50, 'h5-2026-01-01')",
        (iid,),
    )
    late = [t for t in texts(db, evening) if "rise odds" in t]
    assert len(late) == 1 and "2026-11-18" in late[0] and "2026-11-17" in late[0]
    assert not any("rise odds" in t for t in texts(db, early))  # the job has not had its time yet
    db.execute(
        "INSERT INTO rise_odds (day, instrument_id, horizon, prob, pct, model_version) VALUES ('2026-11-18', %s, 5, 0.5, 50, 'h5-2026-01-01')",
        (iid,),
    )
    assert not any("rise odds" in t for t in texts(db, evening))  # caught up
