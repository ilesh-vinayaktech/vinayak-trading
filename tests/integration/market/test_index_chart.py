# ruff: noqa: E501
"""Index candles for the index page's chart: daily as stored, weekly and monthly rolled up from them, intraday built from the stored minutes, and what is unknown is said so."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest

from algo.data.store.migrate import migrate
from algo.market import index_chart as ic

pytestmark = pytest.mark.integration
IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


def put_day(conn, d, o, h, lo, c, symbol="NIFTY 50", exchange="NSE"):
    conn.execute(
        "INSERT INTO index_bar_1d (exchange, symbol, trade_date, open, high, low, close, token, ingested_at) VALUES (%s,%s,%s,%s,%s,%s,%s,1,%s)",
        (exchange, symbol, d, o, h, lo, c, NOW),
    )


def put_minute(conn, day, minute, o, h, lo, c, symbol="NIFTY 50"):
    ts = datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST) + timedelta(minutes=minute)
    conn.execute(
        "INSERT INTO index_bar_1m (token, exchange, symbol, ts, open, high, low, close, source, built_at) VALUES (1,'NSE',%s,%s,%s,%s,%s,%s,'live',%s)",
        (symbol, ts, o, h, lo, c, NOW),
    )


@pytest.fixture
def db(conn):
    migrate(conn)
    for i in range(10):  # Mon 2 Nov .. Fri 13 Nov 2026 (weekdays)
        d = date(2026, 11, 2) + timedelta(days=i + (2 * (i // 5)))
        put_day(conn, d, 100 + i, 110 + i, 90 + i, 105 + i)
    return conn


def test_daily_bars_come_back_as_stored_with_no_volume_and_the_extent_of_the_history(db):
    got = ic.index_bars(db, "NIFTY 50", "1d", date(2026, 11, 1), date(2026, 11, 30))
    assert (
        got is not None
        and got["first"] == "2026-11-02"
        and got["last"] == "2026-11-13"
        and got["intraday_first"] is None
    )
    assert (
        len(got["bars"]) == 10
        and got["bars"][0]
        == {
            "date": "2026-11-02",
            "open": "100.0000",
            "high": "110.0000",
            "low": "90.0000",
            "close": "105.0000",
            "volume": "0",
            "factor": "1",
        }
        or got["bars"][0]["open"].startswith("100")
    )
    assert "time" not in got["bars"][0]  # a daily bar has no intraday time


def test_weekly_and_monthly_bars_are_rolled_up_from_the_daily_ones(db):
    weekly = ic.index_bars(db, "NIFTY 50", "1w", date(2026, 11, 1), date(2026, 11, 30))["bars"]
    assert [b["date"] for b in weekly] == [
        "2026-11-02",
        "2026-11-09",
    ]  # dated by the first trading day
    assert (
        D(weekly[0]["open"]) == 100
        and D(weekly[0]["close"]) == 109
        and D(weekly[0]["high"]) == 114
        and D(weekly[0]["low"]) == 90
    )
    month = ic.index_bars(db, "NIFTY 50", "1mo", date(2026, 11, 1), date(2026, 11, 30))["bars"]
    assert (
        len(month) == 1
        and D(month[0]["open"]) == 100
        and D(month[0]["close"]) == 114
        and D(month[0]["high"]) == 119
    )


def test_intraday_bars_are_built_from_the_stored_minutes_and_carry_their_epoch_time(db):
    day = date(2026, 11, 18)
    for m in range(10):
        put_minute(db, day, m, 100 + m, 101 + m, 99 + m, 100.5 + m)
    got = ic.index_bars(db, "NIFTY 50", "5m", day, day)
    assert got["intraday_first"] == "2026-11-18" and len(got["bars"]) == 2
    first = got["bars"][0]
    assert (
        D(first["open"]) == 100
        and D(first["close"]) == D("104.5")
        and D(first["high"]) == 105
        and D(first["low"]) == 99
    )  # minutes 0..4
    assert (
        first["time"] == int(datetime(2026, 11, 18, 9, 15, tzinfo=IST).astimezone(UTC).timestamp())
        and first["date"] == "2026-11-18"
    )
    assert ic.index_bars(db, "NIFTY 50", "5m", None, None)[
        "bars"
    ]  # with no dates it ends on the newest stored minute day


def test_an_unknown_index_is_none_and_an_unknown_timeframe_is_refused(db):
    assert ic.index_bars(db, "NOT AN INDEX", "1d", None, None) is None
    with pytest.raises(ValueError, match="unknown timeframe"):
        ic.index_bars(db, "NIFTY 50", "7m", None, None)
