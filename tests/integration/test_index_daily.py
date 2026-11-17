# ruff: noqa: E501
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from algo.data import index_daily as m
from algo.data.providers.kite import Candle
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 17, 13, 0, tzinfo=UTC)
D = Decimal
DUMP = (
    b"instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange\n"
    b"256265,1001,NIFTY 50,NIFTY 50,0,,0,0,0,EQ,INDICES,NSE\n"
    b"265,1,SENSEX,SENSEX,0,,0,0,0,EQ,INDICES,BSE\n"
    b"9,9,BHARATBOND-APR30,BB,0,,0,0,0,EQ,INDICES,NSE\n"
    b"8,8,HANGSENG BEES-NAV,HS,0,,0,0,0,EQ,INDICES,NSE\n"
    b"7,7,GOLD,GOLD,0,,0,0,0,EQ,INDICES,MCX\n"
    b"5,5,RELIANCE,R,0,,0,0.05,1,EQ,NSE,NSE\n"
)


class Fake:
    def __init__(self, close="100"):
        self.calls, self.close = [], D(close)

    def historical(self, token, interval, start, end, *, raw_sink=None):
        self.calls.append((token, interval, start.date(), end.date()))
        if token == 265 or end.date() < date(2026, 11, 16):
            return []
        ts = datetime(2026, 11, 16, 3, 45, tzinfo=UTC)  # 09:15 IST
        return [Candle(ts, D(99), D(101), D(98), self.close, D(0), None)]


def test_index_rows_keep_only_nse_bse_real_indexes():
    assert m.index_rows(DUMP) == [(256265, "NSE", "NIFTY 50"), (265, "BSE", "SENSEX")]


def test_load_stores_candle_dates_in_ist_and_upserts(conn):
    migrate(conn)
    rows = m.index_rows(DUMP)
    f = Fake()
    r = m.load_index_days(conn, f, rows, date(1995, 1, 1), date(2026, 11, 17), NOW)
    assert (r.rows, r.empty) == (1, 1)
    assert f.calls[0][1] == "day" and f.calls[0][2] == date(1995, 1, 1)
    assert all((b - a).days < 2000 for _, _, a, b in f.calls)
    got = conn.execute("SELECT exchange, symbol, trade_date, close FROM index_bar_1d").fetchall()
    assert got == [("NSE", "NIFTY 50", date(2026, 11, 16), D(100))]
    m.load_index_days(conn, Fake("105"), rows, date(2026, 11, 1), date(2026, 11, 17), NOW)
    assert conn.execute("SELECT close FROM index_bar_1d").fetchall() == [(D(105),)]


def test_candle_without_price_is_dropped(conn):
    migrate(conn)

    class Pad(Fake):
        def historical(self, *a, **k):
            return [
                Candle(
                    datetime(2026, 11, 16, 3, 45, tzinfo=UTC), D(0), D(0), D(0), D(0), D(5), None
                )
            ]

    r = m.load_index_days(
        conn, Pad(), m.index_rows(DUMP)[:1], date(2026, 11, 1), date(2026, 11, 17), NOW
    )
    assert (r.rows, r.dropped) == (0, 1)


def test_candle_with_zero_close_but_other_prices_is_dropped(conn):
    migrate(conn)

    class Zero(Fake):
        def historical(self, *a, **k):
            return [
                Candle(
                    datetime(2026, 11, 16, 3, 45, tzinfo=UTC), D(77), D(77), D(77), D(0), D(0), None
                )
            ]

    r = m.load_index_days(
        conn, Zero(), m.index_rows(DUMP)[:1], date(2026, 11, 1), date(2026, 11, 17), NOW
    )
    assert (r.rows, r.dropped) == (0, 1)
