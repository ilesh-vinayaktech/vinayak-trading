"""With prices read from Kite, a stock Kite has no candles for (it covers a few hundred names; NSE bhavcopy covers thousands)
must still chart, from bhavcopy, and the answer must say which source it came from."""

from datetime import UTC, date, datetime

import pytest

from algo.api import queries
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 7, tzinfo=UTC)
DAYS = [date(2025, 6, 9), date(2025, 6, 10), date(2025, 6, 11)]


def ts(d):
    return datetime(d.year, d.month, d.day, 3, 45, tzinfo=UTC)


def put(conn, iid, source, close0):
    for i, d in enumerate(DAYS):
        conn.execute(
            "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,adjusted_through,"
            "dataset_version,ingested_at) VALUES (%s,%s,1,2,1,%s,100,%s,%s,1,%s)",
            (iid, ts(d), close0 + i, source, date(2026, 11, 1) if source == "kite" else None, NOW),
        )


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    both, nse_only = repo.add_instrument(x, "BOTH"), repo.add_instrument(x, "NSEONLY")
    put(conn, both, "nse", 10)
    put(
        conn, both, "kite", 100
    )  # Kite's candles differ, so the test can tell which source was read
    put(conn, nse_only, "nse", 50)
    return conn, both, nse_only


def closes(r):
    return [b["close"] for b in r["bars"]]


def test_a_stock_with_kite_candles_reads_kite_when_the_source_is_kite(env, monkeypatch):
    conn, both, _ = env
    monkeypatch.setenv("ALGO_PRICE_SOURCE", "kite")
    r = queries.instrument_bars(conn, both, DAYS[0], DAYS[-1], "none")
    assert closes(r) == ["100", "101", "102"] and r["source"] == "kite"


def test_a_stock_kite_does_not_cover_falls_back_to_bhavcopy_and_says_so(env, monkeypatch):
    conn, _, nse_only = env
    monkeypatch.setenv("ALGO_PRICE_SOURCE", "kite")
    r = queries.instrument_bars(conn, nse_only, DAYS[0], DAYS[-1], "none")
    assert closes(r) == ["50", "51", "52"] and r["source"] == "nse"


def test_with_the_bhavcopy_source_everything_reads_bhavcopy(env, monkeypatch):
    conn, both, nse_only = env
    monkeypatch.setenv("ALGO_PRICE_SOURCE", "bhavcopy")
    r = queries.instrument_bars(conn, both, DAYS[0], DAYS[-1], "none")
    assert closes(r) == ["10", "11", "12"] and r["source"] == "nse"
    assert queries.instrument_bars(conn, nse_only, DAYS[0], DAYS[-1], "none")["source"] == "nse"


def test_the_reader_for_a_stock_is_chosen_the_same_way_for_every_use(env, monkeypatch):
    conn, both, nse_only = env
    monkeypatch.setenv("ALGO_PRICE_SOURCE", "kite")
    assert queries.reader_for(conn, both)[1] == "kite"
    assert queries.reader_for(conn, nse_only)[1] == "nse"
    monkeypatch.setenv("ALGO_PRICE_SOURCE", "bhavcopy")
    assert queries.reader_for(conn, both)[1] == "nse"
