from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from algo.core.clock import SimClock
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.live.bar_store import save_bars, save_quotes, save_status
from algo.live.ticks import Tick
from tests.support.portal import add_user, make_app, settings, sign_in

pytestmark = pytest.mark.integration
START = datetime(2026, 11, 12, 4, 30, tzinfo=UTC)  # 10:00 IST on a Thursday
TOKEN = 738561


@pytest.fixture
def env(conn, pg_url, tmp_path):
    migrate(conn)
    clock = SimClock(START)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    iid = repo.add_instrument(x, "RELIANCE", isin="INE002A01018")
    add_user(conn, clock, "VIEWER", "viewer@example.com")
    return conn, make_app(pg_url, tmp_path, portal=settings(clock)), clock, iid


def feed(conn, state="CONNECTED", last_tick_at=START):
    save_status(
        conn, state, "497 instruments", subscribed=497, last_tick_at=last_tick_at, last_bar_at=None,
        ticks=10, bars=1, bad_frames=0, late_ticks=0, now=START,
    )  # fmt: skip


def quote(conn, iid, price="2875.5", when=START):
    t = Tick(TOKEN, D(price), 1_234_567, when, D("2860"), D("2880"), D("2855"), D("2865"))
    save_quotes(conn, {TOKEN: t}, {TOKEN: iid}, when)


def test_signing_in_is_needed_and_an_unknown_stock_is_not_found(env):
    conn, app, _, iid = env
    assert TestClient(app).get(f"/api/live/{iid}").status_code == 401
    c = sign_in(app, "viewer@example.com")
    assert c.get(f"/api/live/{iid}").status_code == 200
    assert c.get("/api/live/999999").status_code == 404


def test_before_any_tick_there_is_no_quote_and_the_feed_is_not_live(env):
    conn, app, _, iid = env
    d = sign_in(app, "viewer@example.com").get(f"/api/live/{iid}").json()
    assert d == {
        "today": "2026-11-12",
        "candle": None,
        "live": False,
        "feed": {"state": None, "last_tick_at": None},
        "session_date": None,
        "quote": None,
    }


def test_a_fresh_quote_from_a_connected_feed_is_live_with_the_exchanges_day_figures(env):
    conn, app, clock, iid = env
    feed(conn, last_tick_at=START)
    quote(conn, iid, when=START)
    clock.advance(timedelta(seconds=3))
    d = sign_in(app, "viewer@example.com").get(f"/api/live/{iid}").json()
    assert d["live"] is True and d["feed"] == {
        "state": "CONNECTED",
        "last_tick_at": "2026-11-12T04:30:00+00:00",
    }
    assert d["session_date"] == "2026-11-12"
    assert d["quote"] == {
        "ltp": "2875.5", "open": "2860", "high": "2880", "low": "2855", "prev_close": "2865",
        "volume": "1234567", "updated_at": "2026-11-12T04:30:00+00:00",
    }  # fmt: skip


def test_the_last_quote_is_still_served_but_not_called_live_when_the_feed_is_down_or_silent(env):
    conn, app, clock, iid = env
    quote(conn, iid, when=START)
    c = sign_in(app, "viewer@example.com")
    feed(conn, state="STOPPED", last_tick_at=START)
    assert c.get(f"/api/live/{iid}").json()["live"] is False  # the feed says it stopped
    feed(conn, state="CONNECTED", last_tick_at=START)
    clock.advance(timedelta(seconds=45))
    d = c.get(f"/api/live/{iid}").json()
    assert d["live"] is False and d["quote"]["ltp"] == "2875.5"  # connected but silent for 45 s


def test_a_quote_from_an_earlier_day_carries_its_own_session_date_so_a_chart_can_tell_it_is_old(
    env,
):
    conn, app, _, iid = env
    feed(conn, state="STOPPED", last_tick_at=START - timedelta(days=1))
    quote(conn, iid, when=START - timedelta(days=1))
    d = sign_in(app, "viewer@example.com").get(f"/api/live/{iid}").json()
    assert (d["live"], d["session_date"]) == (False, "2026-11-11")


def put_day(conn, iid, d, o, c):
    from tests.support.bt import put_bars

    put_bars(conn, iid, {d: (D(o), D(c))})


def live_quote(conn, iid, ltp, o, h, low, volume, building=None, when=START):
    t = Tick(TOKEN, D(ltp), volume, when, D(o), D(h), D(low), D(o))
    save_quotes(conn, {TOKEN: t}, {TOKEN: iid}, when, {TOKEN: building} if building else None)


def minute_bar(m, o, h, low, c, v):
    from algo.live.bars import LiveBar

    return LiveBar(TOKEN, START + timedelta(minutes=m), D(o), D(h), D(low), D(c), v, 3, False)


@pytest.fixture
def week(env):
    conn, app, clock, iid = env
    feed(conn)
    days = ((date(2026, 11, 2), 90, 95), (date(2026, 11, 6), 95, 100), (date(2026, 11, 9), 100, 103),
            (date(2026, 11, 10), 103, 108), (date(2026, 11, 11), 108, 96))  # fmt: skip
    for d, o, c in days:
        put_day(conn, iid, d, o, c)  # 10,000,000 shares a day
    live_quote(conn, iid, "98", "96", "100", "94", 40)
    return conn, sign_in(app, "viewer@example.com"), iid


def candle(c, iid, timeframe, **params):
    r = c.get(f"/api/live/{iid}", params={"timeframe": timeframe, **params})
    assert r.status_code == 200, r.text
    return r.json()


def test_todays_daily_candle_is_the_exchanges_day_with_the_last_price(week):
    _, c, iid = week
    d = candle(c, iid, "1d")
    assert d["today"] == "2026-11-12"
    assert d["candle"] == {
        "time": "2026-11-12",
        "open": "96",
        "high": "100",
        "low": "94",
        "close": "98",
        "volume": "40",
    }


def test_this_weeks_candle_is_monday_to_today_like_a_brokers_weekly_chart(week):
    _, c, iid = week
    assert candle(c, iid, "1w")["candle"] == {
        "time": "2026-11-09", "open": "100", "high": "108", "low": "94", "close": "98", "volume": "30000040",
    }  # fmt: skip


def test_this_months_candle_runs_from_the_months_first_trading_day_to_today(week):
    _, c, iid = week
    assert candle(c, iid, "1mo")["candle"] == {
        "time": "2026-11-02", "open": "90", "high": "108", "low": "90", "close": "98", "volume": "50000040",
    }  # fmt: skip


def test_the_current_intraday_bar_merges_todays_finished_live_minutes_with_the_one_still_building(
    env,
):
    conn, app, _, iid = env
    feed(conn)
    done = [
        minute_bar(m, 100 + m, 102 + m, 99 + m, 101 + m, 10) for m in range(-5, 0)
    ]  # 09:55 .. 09:59 IST
    save_bars(conn, done, {TOKEN: iid}, START)
    live_quote(
        conn, iid, "97", "90", "110", "88", 999, building=minute_bar(0, 96, 98, 95, 97, 7)
    )  # 10:00 IST
    c = sign_in(app, "viewer@example.com")
    ten = candle(c, iid, "10m")["candle"]  # 09:55 .. 10:04 holds them all
    assert ten == {"time": int((START - timedelta(minutes=5)).timestamp()), "open": "95", "high": "101",
                   "low": "94", "close": "97", "volume": "57"}  # fmt: skip
    one = candle(c, iid, "1m")["candle"]
    assert (one["time"], one["open"], one["close"], one["volume"]) == (
        int(START.timestamp()),
        "96",
        "97",
        "7",
    )
    bars = c.get(
        f"/api/instruments/{iid}/bars",
        params={"start": "2026-11-12", "end": "2026-11-12", "timeframe": "5m"},
    ).json()
    assert (
        [(b["time"], b["open"], b["close"], b["volume"]) for b in bars["bars"]]
        == [
            (int((START - timedelta(minutes=5)).timestamp()), "95", "100", "50"),
        ]
    )  # the chart's own 5-minute bars include today's finished live minutes (stored history has none yet)


def test_no_quote_means_no_candle_and_a_timeframe_must_be_one_the_chart_knows(env):
    conn, app, _, iid = env
    c = sign_in(app, "viewer@example.com")
    assert candle(c, iid, "1w")["candle"] is None
    assert c.get(f"/api/live/{iid}", params={"timeframe": "7m"}).status_code == 422
    assert c.get(f"/api/live/{iid}", params={"adjust": "magic"}).status_code == 422


def test_a_day_the_stored_minute_history_already_has_ignores_the_live_minutes(env):
    conn, app, _, iid = env
    conn.execute(
        "INSERT INTO bar_1m (instrument_id,ts,open,high,low,close,volume,source,adjusted_through,dataset_version,ingested_at)"
        " VALUES (%s,%s,500,500,500,500,1,'kite','2026-11-12',1,%s)",
        (iid, START - timedelta(minutes=45), START),  # 09:15 IST, from Kite's history
    )
    save_bars(conn, [minute_bar(-5, 100, 101, 99, 100, 10)], {TOKEN: iid}, START)  # 09:55 IST, live
    c = sign_in(app, "viewer@example.com")
    bars = c.get(
        f"/api/instruments/{iid}/bars",
        params={"start": "2026-11-12", "end": "2026-11-12", "timeframe": "1m"},
    ).json()
    assert [b["close"] for b in bars["bars"]] == [
        "500"
    ]  # the vetted history wins for the whole day


def test_quotes_give_the_live_price_with_the_change_from_the_previous_close_and_fall_back_to_the_last_close(
    env,
):
    conn, app, _, iid = env
    repo = InstrumentRepo(conn)
    other = repo.add_instrument(
        repo.add_exchange("XBSE", "IN", "Asia/Kolkata", "INR", "BSE"), "TCS", isin="INE467B01029"
    )
    lonely = repo.add_instrument(
        repo.add_exchange("XNSE2", "IN", "Asia/Kolkata", "INR", "NSE2"),
        "NODATA",
        isin="INE000000001",
    )
    quote(conn, iid, "2900")  # previous close in the helper is 2865
    put_day(conn, other, date(2026, 11, 10), "3900", "3910")
    put_day(conn, other, date(2026, 11, 11), "3910", "3939")
    c = sign_in(app, "viewer@example.com")
    got = c.get(f"/api/live/quotes?ids={iid},{other},{lonely}").json()["quotes"]
    assert (
        got[str(iid)]["source"] == "live"
        and got[str(iid)]["ltp"] == "2900"
        and got[str(iid)]["prev_close"] == "2865"
    )
    assert round(got[str(iid)]["change_pct"], 3) == round(35 / 2865 * 100, 3)
    assert (
        got[str(other)]["source"] == "close"
        and got[str(other)]["ltp"] == "3939"
        and got[str(other)]["prev_close"] == "3910"
    )
    assert str(lonely) not in got  # neither a quote nor a bar: left out
    assert c.get("/api/live/quotes?ids=abc").status_code == 400
    assert TestClient(app).get("/api/live/quotes?ids=1").status_code == 401


def test_the_index_cards_show_live_quotes_with_a_minute_line_and_fall_back_to_daily_closes(env):
    from algo.live.bars import LiveBar
    from algo.live.index_store import save_index_bars, save_index_quotes

    conn, app, _, _ = env
    names = {256265: ("NSE", "NIFTY 50")}
    feed(conn)
    save_index_quotes(
        conn,
        {
            256265: Tick(
                256265, D("25100"), None, START, D("25000"), D("25150"), D("24950"), D("25020")
            )
        },
        names,
        START,
    )
    bar = LiveBar(
        256265, START.replace(minute=29), D("25090"), D("25110"), D("25080"), D("25100"), 0, 5, True
    )
    save_index_bars(conn, [bar], names, START)
    for d, close in ((date(2026, 11, 10), "82000"), (date(2026, 11, 11), "82500")):
        conn.execute(
            "INSERT INTO index_bar_1d (exchange, symbol, trade_date, open, high, low, close, token, ingested_at) VALUES ('BSE','SENSEX',%s,%s,%s,%s,%s,265,%s)",
            (d, close, close, close, close, START),
        )
    c = sign_in(app, "viewer@example.com")
    body = c.get("/api/live/indices").json()
    cards = {x["symbol"]: x for x in body["indices"]}
    assert body["live"] is True and list(cards) == ["NIFTY 50", "SENSEX"]
    n = cards["NIFTY 50"]
    assert (n["source"], n["ltp"], n["prev_close"], n["change"], n["spark"]) == (
        "live",
        "25100",
        "25020",
        "80",
        [25100.0],
    )
    s = cards["SENSEX"]
    assert (s["source"], s["ltp"], s["change"], s["spark"]) == ("daily", "82500", "500", [])
