"""The stocks to download from Kite: every active equity in our own instrument master, not just an index list. Mapping extra
stocks must not switch them on for the live feed (the feed follows `active`)."""

from datetime import UTC, date, datetime

import pytest

from algo.data.kite_ingest import map_universe, master_universe, upsert_kite_instruments
from algo.data.providers.kite import KiteInstrument
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 12, 4, 0, tzinfo=UTC)


def kite(token, symbol):
    return KiteInstrument(token, token + 1, symbol, symbol, "NSE", "NSE", "EQ")


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    ids = {
        "AAA": repo.add_instrument(x, "AAA", isin="INE000000011"),
        "BBB": repo.add_instrument(x, "BBB", isin="INE000000029"),
        "FUND": repo.add_instrument(x, "FUND", isin="INF000000010"),
        "GONE": repo.add_instrument(x, "GONE", isin="INE000000037"),
    }
    conn.execute(
        "UPDATE instrument SET status='delisted', delisted_on=%s WHERE instrument_id=%s",
        (date(2024, 1, 1), ids["GONE"]),
    )
    return conn, ids


def test_the_master_universe_is_every_active_equity_and_leaves_out_funds_and_delisted_stocks(env):
    conn, _ = env
    assert master_universe(conn) == [
        ("AAA", "INE000000011", "EQ"),
        ("BBB", "INE000000029", "EQ"),
    ]


def test_extra_stocks_are_stored_inactive_so_the_live_feed_does_not_follow_them(env):
    conn, ids = env
    upsert_kite_instruments(
        conn, [(kite(101, "AAA"), ids["AAA"])], NOW
    )  # a feed stock: active by default
    mapped = map_universe(conn, [kite(101, "AAA"), kite(102, "BBB")], master_universe(conn)).mapped
    assert {k.tradingsymbol for k, _ in mapped} == {"AAA", "BBB"}
    upsert_kite_instruments(conn, mapped, NOW, active=False)
    rows = dict(conn.execute("SELECT tradingsymbol, active FROM kite_instrument").fetchall())
    assert rows == {
        "AAA": True,
        "BBB": False,
    }  # the existing feed stock keeps its flag; the new one is history-only


def test_a_stock_kite_lists_under_its_be_series_is_still_matched_from_our_master(env):
    conn, _ = env
    mapped = map_universe(
        conn, [kite(201, "AAA-BE"), kite(202, "BBB")], master_universe(conn)
    ).mapped
    assert {k.tradingsymbol for k, _ in mapped} == {
        "AAA-BE",
        "BBB",
    }  # we do not know AAA's series; Kite names it AAA-BE
