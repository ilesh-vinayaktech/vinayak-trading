# ruff: noqa: E501
"""The index quote and minute-bar store: which indices are followed, a quote replaced in place, a minute written once, and Kite candles filling gaps."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from algo.data.providers.kite import Candle
from algo.data.store.migrate import migrate
from algo.live.bars import LiveBar
from algo.live.index_store import (
    TRACKED,
    index_tokens,
    load_kite_minutes,
    read_cards,
    save_index_bars,
    save_index_quotes,
)
from algo.live.ticks import Tick

pytestmark = pytest.mark.integration
OPEN = datetime(2026, 11, 12, 3, 45, tzinfo=UTC)  # 09:15 IST
NIFTY, SENSEX = 256265, 265
NAMES = {NIFTY: ("NSE", "NIFTY 50"), SENSEX: ("BSE", "SENSEX")}


def at(m: int) -> datetime:
    return OPEN + timedelta(minutes=m)


def bar(token, m, close, ticks=1):
    return LiveBar(token, at(m), D(close), D(close), D(close), D(close), 0, ticks, True)


@pytest.fixture
def db(conn):
    migrate(conn)
    return conn


def test_tracked_indices_take_their_tokens_from_the_newest_daily_row_and_an_unknown_one_is_skipped(
    db,
):
    for exchange, symbol, token, day in (
        ("NSE", "NIFTY 50", 111, date(2026, 11, 1)),
        ("NSE", "NIFTY 50", NIFTY, date(2026, 11, 2)),
        ("BSE", "SENSEX", SENSEX, date(2026, 11, 2)),
    ):
        db.execute(
            "INSERT INTO index_bar_1d (exchange, symbol, trade_date, open, high, low, close, token, ingested_at) VALUES (%s,%s,%s,1,1,1,1,%s,%s)",
            (exchange, symbol, day, token, OPEN),
        )
    assert index_tokens(db) == {
        NIFTY: ("NSE", "NIFTY 50"),
        SENSEX: ("BSE", "SENSEX"),
    }  # the newest token wins; the other tracked indices have no rows
    assert len(TRACKED) > 2


def test_a_quote_is_replaced_in_place_and_a_price_only_tick_keeps_the_days_figures(db):
    full = Tick(NIFTY, D("25100"), None, OPEN, D("25000"), D("25150"), D("24950"), D("25020"))
    save_index_quotes(db, {NIFTY: full}, NAMES, OPEN)
    save_index_quotes(db, {NIFTY: Tick(NIFTY, D("25110"), None, None)}, NAMES, at(1))
    save_index_quotes(
        db, {999: Tick(999, D("1"), None, None)}, NAMES, at(1)
    )  # not followed: ignored
    rows = db.execute(
        "SELECT ltp, day_open, day_high, day_low, prev_close, updated_at FROM index_live_quote"
    ).fetchall()
    assert rows == [(D("25110"), D("25000"), D("25150"), D("24950"), D("25020"), at(1))]


def test_a_minute_is_written_once_and_the_cards_read_the_line_in_order(db):
    assert save_index_bars(db, [bar(NIFTY, 0, "100"), bar(NIFTY, 1, "101")], NAMES, at(2)) == 2
    assert (
        save_index_bars(db, [bar(NIFTY, 1, "999"), bar(5, 0, "1")], NAMES, at(2)) == 0
    )  # a stored minute stays; an unfollowed token is ignored
    save_index_quotes(
        db,
        {NIFTY: Tick(NIFTY, D("101"), None, OPEN, D("100"), D("102"), D("99"), D("98"))},
        NAMES,
        at(2),
    )
    cards = read_cards(db, OPEN - timedelta(hours=4), OPEN + timedelta(hours=20))
    assert [(c["symbol"], c["ltp"], c["prev_close"], c["spark"]) for c in cards] == [
        ("NIFTY 50", D("101"), D("98"), [100.0, 101.0])
    ]
    assert (
        read_cards(db, OPEN + timedelta(days=1), OPEN + timedelta(days=2))[0]["spark"] == []
    )  # another day has no line


def test_kite_candles_fill_missing_minutes_but_not_the_one_still_building_or_one_already_stored(db):
    class Fake:
        def historical(self, token, interval, start, end):
            assert interval == "minute"
            return [
                Candle(at(m), D(100 + m), D(101 + m), D(99 + m), D(100 + m), D(0), None)
                for m in (0, 1, 2)
            ]

    save_index_bars(db, [bar(NIFTY, 1, "7", ticks=3)], {NIFTY: NAMES[NIFTY]}, at(2))
    assert (
        load_kite_minutes(
            db, Fake(), {NIFTY: NAMES[NIFTY]}, at(0), at(3), at(2) + timedelta(seconds=30)
        )
        == 1
    )
    assert db.execute("SELECT ts, close, source FROM index_bar_1m ORDER BY ts").fetchall() == [
        (at(0), D(100), "kite"),
        (at(1), D(7), "live"),
    ]
