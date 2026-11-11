import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import psycopg
import pytest

from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.live.bar_store import read_status, save_bars, save_status, token_map
from algo.live.bars import LiveBar

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 12, 4, 0, tzinfo=UTC)
OPEN = datetime(2026, 11, 12, 3, 45, tzinfo=UTC)


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    a = repo.add_instrument(x, "RELIANCE", isin="INE002A01018")
    b = repo.add_instrument(x, "TCS", isin="INE467B01029")
    for token, sym, iid in ((738561, "RELIANCE", a), (2953217, "TCS", b), (999, "NOMATCH", None)):
        conn.execute(
            "INSERT INTO kite_instrument (instrument_token, exchange_token, tradingsymbol, name, instrument_id, refreshed_at) VALUES (%s,1,%s,%s,%s,%s)",
            (token, sym, sym, iid, NOW),
        )
    return conn, a, b


def bar(token, minute=0, close="101", volume=500, partial=False):
    return LiveBar(
        token,
        OPEN + timedelta(minutes=minute),
        D("100"),
        D("102"),
        D("99"),
        D(close),
        volume,
        7,
        partial,
    )


def test_tokens_map_to_instrument_ids_and_unmatched_tokens_are_left_out(env):
    conn, a, b = env
    assert token_map(conn) == {738561: a, 2953217: b}


def test_bars_are_saved_once_unknown_instruments_are_skipped_and_a_resend_changes_nothing(env):
    conn, a, b = env
    ids = token_map(conn)
    bars = [bar(738561), bar(2953217, partial=True), bar(12345)]  # 12345 is not one of ours
    assert save_bars(conn, bars, ids, NOW) == 2
    assert save_bars(conn, bars, ids, NOW + timedelta(seconds=5)) == 0  # a bar is never rewritten
    row = conn.execute(
        "SELECT open, high, low, close, volume, ticks, partial, built_at FROM live_bar_1m WHERE instrument_id=%s",
        (b,),
    ).fetchone()
    assert row == (D(100), D(102), D(99), D(101), D(500), 7, True, NOW)
    assert save_bars(conn, [], ids, NOW) == 0


def test_each_new_bar_notifies_listeners_with_instrument_and_minute(env, pg_url):
    conn, a, _ = env
    got: list[str] = []
    ready = threading.Event()

    def listen():
        with psycopg.connect(pg_url, autocommit=True) as c:
            c.execute("LISTEN live_bar")
            ready.set()
            for n in c.notifies(timeout=5, stop_after=1):
                got.append(n.payload)

    t = threading.Thread(target=listen)
    t.start()
    ready.wait(5)
    save_bars(conn, [bar(738561)], token_map(conn), NOW)
    t.join(6)
    assert got == [f"{a},{OPEN.isoformat()}"]


def test_the_status_is_one_row_that_is_replaced_each_time(env):
    conn, *_ = env
    assert read_status(conn) is None
    kw = dict(
        subscribed=497,
        last_tick_at=NOW,
        last_bar_at=None,
        ticks=10,
        bars=2,
        bad_frames=1,
        late_ticks=3,
    )
    save_status(conn, "STARTING", "", now=NOW, **kw)
    save_status(conn, "CONNECTED", "497 instruments", now=NOW + timedelta(seconds=5), **kw)
    assert read_status(conn) == {
        "state": "CONNECTED",
        "detail": "497 instruments",
        "subscribed": 497,
        "last_tick_at": NOW,
        "last_bar_at": None,
        "ticks": 10,
        "bars": 2,
        "bad_frames": 1,
        "late_ticks": 3,
        "updated_at": NOW + timedelta(seconds=5),
    }
    assert conn.execute("SELECT count(*) FROM feed_status").fetchone() == (1,)
    with pytest.raises(psycopg.errors.CheckViolation):
        save_status(conn, "BOGUS", "", now=NOW, **kw)
