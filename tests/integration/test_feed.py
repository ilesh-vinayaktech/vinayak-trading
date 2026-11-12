import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from algo.core.clock import SimClock
from algo.data.providers.kite import KiteTokenExpired
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.live.bar_store import read_quote, read_status, token_map
from algo.live.feed import Feed
from tests.unit.live.test_ticks import frame, full

pytestmark = pytest.mark.integration
OPEN = datetime(2026, 11, 12, 3, 45, tzinfo=UTC)  # 09:15 IST
RELIANCE, TCS, SBIN = 738561, 2953217, 779521


def at(minute: int, second: int = 0) -> datetime:
    return OPEN + timedelta(minutes=minute, seconds=second)


def ticks(minute, second, price, volume, token=RELIANCE):
    epoch = int(at(minute, second).timestamp())
    return frame(full(token=token, ltp=int(price * 100), volume=volume, ts=epoch))


@dataclass
class Advance:
    to: datetime


@dataclass
class Silence:
    seconds: float


class Drop:
    pass


@dataclass
class Do:
    fn: object


class Script:
    """A scripted socket: frames to deliver, and what happens to the clock and the connection between them."""

    def __init__(self, clock, *items):
        self.clock, self.items, self.sent = clock, list(items), []

    async def send(self, message):
        self.sent.append(json.loads(message))

    async def recv(self):
        while True:
            if not self.items:
                raise ConnectionError("script ended")
            item = self.items.pop(0)
            if isinstance(item, Advance):
                self.clock.advance_to(item.to)
            elif isinstance(item, Silence):
                self.clock.advance(timedelta(seconds=item.seconds))
                raise TimeoutError
            elif isinstance(item, Drop):
                raise ConnectionError("dropped")
            elif isinstance(item, Do):
                item.fn()
            else:
                return item


class Rig:
    def __init__(self, conn, a, b):
        self.conn, self.clock = conn, SimClock(OPEN)
        self.ids = {RELIANCE: a, TCS: b}
        self.sleeps: list[float] = []

    def feed(self, *connections, **kw):
        queue = list(connections)

        @asynccontextmanager
        async def connect():
            item = queue.pop(0)
            if isinstance(item, BaseException):
                raise item
            yield item

        async def sleep(seconds):
            self.sleeps.append(seconds)

        kw.setdefault("batch", 500)
        return Feed(connect, self.conn, self.ids, self.clock, sleep=sleep, **kw)

    def script(self, *items):
        return Script(self.clock, *items)

    def bars(self):
        return self.conn.execute(
            "SELECT ts, open, high, low, close, volume, ticks, partial FROM live_bar_1m ORDER BY instrument_id, ts"
        ).fetchall()


@pytest.fixture
def rig(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    a = repo.add_instrument(x, "RELIANCE", isin="INE002A01018")
    b = repo.add_instrument(x, "TCS", isin="INE467B01029")
    for token, sym, iid in ((RELIANCE, "RELIANCE", a), (TCS, "TCS", b)):
        conn.execute(
            "INSERT INTO kite_instrument (instrument_token, exchange_token, tradingsymbol, name, instrument_id, refreshed_at) VALUES (%s,1,%s,%s,%s,%s)",
            (token, sym, sym, iid, OPEN),
        )
    return Rig(conn, a, b)


def test_it_subscribes_in_batches_and_asks_for_full_quotes(rig):
    sock = rig.script(Do(lambda: feed.stop()))
    feed = rig.feed(sock, batch=1)
    asyncio.run(feed.run())
    assert sock.sent == [
        {"a": "subscribe", "v": [RELIANCE]},
        {"a": "mode", "v": ["full", [RELIANCE]]},
        {"a": "subscribe", "v": [TCS]},
        {"a": "mode", "v": ["full", [TCS]]},
    ]


def test_ticks_become_bars_that_are_stored_and_announced_and_the_status_says_how_it_went(rig):
    sock = rig.script(
        Advance(at(0, 5)), ticks(0, 5, 100, 1000),
        Advance(at(0, 30)), ticks(0, 30, 102, 1200),
        Advance(at(1, 5)), ticks(1, 5, 101, 1500),
        Advance(at(2, 5)), Silence(0),  # the quiet second after minute 1 ended lets it close
        Do(lambda: feed.stop()),
    )  # fmt: skip
    feed = rig.feed(sock, dead_after=600)
    assert asyncio.run(feed.run()) == "STOPPED"
    assert rig.bars() == [
        (at(0), D(100), D(102), D(100), D(102), D(200), 2, False),
        (at(1), D(101), D(101), D(101), D(101), D(300), 1, False),
    ]
    s = read_status(rig.conn)
    assert (s["state"], s["subscribed"], s["ticks"], s["bars"], s["bad_frames"]) == (
        "STOPPED",
        2,
        3,
        2,
        0,
    )
    assert s["last_tick_at"] == at(1, 5) and s["last_bar_at"] is not None


def test_bad_frames_unknown_instruments_and_server_notices_are_counted_not_fatal(rig):
    seen = []
    sock = rig.script(
        b"\x00\x01",  # promises a packet, has none
        ticks(0, 1, 50, 10, token=SBIN),  # not an instrument of ours
        b"\x00",  # heartbeat
        json.dumps({"type": "error", "data": "Token invalid for subscription"}),
        "not json at all",
        json.dumps({"type": "order", "data": {}}),
        ticks(0, 2, 100, 10),
        Do(lambda: feed.stop()),
    )
    feed = rig.feed(sock, frame_sink=lambda data, when: seen.append((data[:2], when)))
    asyncio.run(feed.run())
    s = read_status(rig.conn)
    assert (s["bad_frames"], s["ticks"]) == (1, 1)
    assert "Token invalid for subscription" in s["detail"]
    assert len(seen) == 4  # every binary frame, good or bad, reaches the sink


def test_a_silent_connection_is_dropped_and_reopened_and_the_volume_gap_is_not_dumped_in_one_bar(
    rig,
):
    first = rig.script(
        Advance(at(30)), ticks(30, 0, 100, 1000),
        Silence(20), Silence(20),  # 40 s of nothing, past the 30 s limit
    )  # fmt: skip
    second = rig.script(
        Advance(at(34)), ticks(34, 0, 101, 9000),  # 8000 traded while we were away
        Advance(at(34, 50)), ticks(34, 50, 102, 9100),
        Advance(at(35, 3)), Silence(0), Do(lambda: feed.stop()),
    )  # fmt: skip
    feed = rig.feed(first, second, dead_after=30)
    asyncio.run(feed.run())
    assert rig.sleeps == [1]
    assert [(r[0], r[5], r[7]) for r in rig.bars()] == [
        (at(30), D(0), True),
        (at(34), D(100), True),
    ]
    assert len(second.sent) == 2  # it subscribed again


def test_reconnect_waits_grow_up_to_a_cap_and_start_over_once_data_flows_again(rig):
    failures = [OSError("refused")] * 7
    good = rig.script(ticks(0, 1, 100, 10), Drop())
    bad = rig.script(Drop())
    final = rig.script(Do(lambda: feed.stop()))
    feed = rig.feed(*failures, good, bad, final)
    asyncio.run(feed.run())
    assert rig.sleeps == [1, 2, 4, 8, 16, 32, 60, 1, 2]


def test_an_expired_token_stops_the_service_with_a_clear_state_and_no_retry(rig):
    feed = rig.feed(KiteTokenExpired("refused"))
    assert asyncio.run(feed.run()) == "TOKEN_EXPIRED"
    s = read_status(rig.conn)
    assert s["state"] == "TOKEN_EXPIRED" and "connect" in s["detail"].lower()
    assert rig.sleeps == []


def test_it_stops_by_itself_at_the_end_time_after_closing_the_last_bars(rig):
    end = at(375, 30)  # 15:30:30 IST
    sock = rig.script(
        Advance(at(374, 10)), ticks(374, 10, 100, 10),
        Advance(end), Silence(0),
        ticks(0, 0, 1, 1),  # never read: the service has already stopped
    )  # fmt: skip
    feed = rig.feed(sock, until=end, dead_after=600)
    assert asyncio.run(feed.run()) == "STOPPED"
    assert [r[0] for r in rig.bars()] == [at(374)]
    assert read_status(rig.conn)["detail"] == "reached the end time"


def test_the_status_is_refreshed_while_running_and_connections_are_not_confused_between_runs(rig):
    sock = rig.script(Silence(6), Silence(6), Do(lambda: feed.stop()))
    feed = rig.feed(sock, status_every=5)
    asyncio.run(feed.run())
    assert read_status(rig.conn)["updated_at"] == OPEN + timedelta(seconds=12)
    assert token_map(rig.conn) == rig.ids


def test_the_latest_price_of_each_stock_is_published_every_couple_of_seconds_for_the_charts(rig):
    sock = rig.script(
        Advance(at(0, 5)), ticks(0, 5, 100, 1000),
        Advance(at(0, 6)), ticks(0, 6, 101, 1100),
        Advance(at(0, 9)), ticks(0, 9, 102, 1300),
        Do(lambda: feed.stop()),
    )  # fmt: skip
    feed = rig.feed(sock, dead_after=600, quote_every=2.0)
    asyncio.run(feed.run())
    q = read_quote(rig.conn, rig.ids[RELIANCE])
    assert (q["ltp"], q["volume"], q["updated_at"]) == (D(102), 1300, at(0, 9))
    assert (q["day_open"], q["day_high"], q["day_low"], q["prev_close"]) == (
        D("2860"),
        D("2880"),
        D("2855"),
        D("2865"),
    )
    assert read_quote(rig.conn, rig.ids[TCS]) is None  # no tick, no quote


def test_a_price_that_arrived_inside_the_quiet_gap_is_still_published_when_the_feed_stops(rig):
    sock = rig.script(
        Advance(at(0, 5)), ticks(0, 5, 100, 1000),
        Advance(at(0, 6)), ticks(0, 6, 101, 1100),  # one second after the last publish: not due yet
        Do(lambda: feed.stop()),
    )  # fmt: skip
    feed = rig.feed(sock, dead_after=600, quote_every=2.0)
    asyncio.run(feed.run())
    assert read_quote(rig.conn, rig.ids[RELIANCE])["ltp"] == D(101)


def test_the_published_quote_includes_the_minute_still_being_built(rig):
    sock = rig.script(
        Advance(at(0, 5)), ticks(0, 5, 100, 1000),
        Advance(at(0, 30)), ticks(0, 30, 104, 1200),
        Do(lambda: feed.stop()),
    )  # fmt: skip
    feed = rig.feed(sock, dead_after=600, quote_every=2.0)
    asyncio.run(feed.run())
    q = read_quote(rig.conn, rig.ids[RELIANCE])
    assert (q["minute_ts"], q["minute_open"], q["minute_high"], q["minute_low"], q["ltp"]) == (
        at(0), D(100), D(104), D(100), D(104),
    )  # fmt: skip


def test_more_instruments_than_one_kite_connection_carries_are_refused_up_front(rig):
    with pytest.raises(ValueError, match="3000"):
        Feed(lambda: None, rig.conn, {i: 1 for i in range(3001)}, rig.clock)
