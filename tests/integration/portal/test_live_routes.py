from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from algo.core.clock import SimClock
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.live.bar_store import save_quotes, save_status
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
