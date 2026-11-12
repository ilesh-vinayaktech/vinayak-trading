"""AMFI ranking lists stored, matched to our instruments, and asked "which segment was this stock in on day X"."""

from datetime import UTC, date, datetime
from decimal import Decimal as D

import pytest

from algo.data.amfi_caps import CapList, CapRow
from algo.data.market_caps import list_status, load_list, segments_on
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    big = repo.add_instrument(x, "BIG", isin="INE000000011")
    renamed = repo.add_instrument(
        x, "NEWNAME", isin="INE000000099"
    )  # its ISIN changed after the list
    repo.add_alias(renamed, "nse", "OLDNAME", date(2010, 1, 1), date(2025, 1, 1))
    repo.add_alias(renamed, "nse", "NEWNAME", date(2025, 1, 1))
    tiny = repo.add_instrument(x, "TINY", isin="INE000000033")
    return conn, big, renamed, tiny


def row(rank, isin, nse, cap="1"):
    return CapRow(rank, isin, nse, f"Co {rank}", D(cap))


def h1_2024(*extra):
    rows = [
        row(1, "INE000000011", "BIG", "500000"),
        row(150, "INE0000000ZZ", "OLDNAME"),
        row(600, "INE000000033", "TINY"),
    ]
    return CapList(date(2024, 6, 30), tuple(rows + list(extra)))


def test_a_list_is_stored_with_each_company_matched_by_isin_or_by_the_nse_symbol_it_had_then(env):
    conn, big, renamed, tiny = env
    r = load_list(
        conn,
        h1_2024(row(700, None, None), row(800, "INE00000ZZZZ", None), row(900, None, "GHOST")),
        "https://amfi/x.xlsx",
        "sha",
        NOW,
    )
    assert (r.companies, r.matched) == (
        6,
        3,
    )  # BSE-only ones (no ISIN we know, no NSE symbol) match nothing
    status = list_status(conn)
    assert status == [{"period_end": date(2024, 6, 30), "effective_from": date(2024, 8, 1), "companies": 6, "matched": 3,
                       "source_url": "https://amfi/x.xlsx"}]  # fmt: skip


def test_the_segment_on_a_day_comes_from_the_list_in_force_that_day_and_none_before_the_first(env):
    conn, big, renamed, tiny = env
    load_list(conn, h1_2024(), "u1", "s1", NOW)
    load_list(
        conn,
        CapList(
            date(2024, 12, 31), (row(1, "INE000000033", "TINY"), row(260, "INE000000011", "BIG"))
        ),
        "u2",
        "s2",
        NOW,
    )
    assert segments_on(conn, date(2024, 7, 31)) == {}  # the Jun 2024 list is relied on from 1 Aug
    assert segments_on(conn, date(2024, 8, 1)) == {
        big: ("large", 1),
        renamed: ("mid", 150),
        tiny: ("micro", 600),
    }
    assert segments_on(conn, date(2025, 2, 1)) == {
        tiny: ("large", 1),
        big: ("small", 260),
    }  # the next list replaces it whole


def test_reloading_a_list_replaces_it_rather_than_adding_to_it(env):
    conn, *_ = env
    load_list(conn, h1_2024(), "u1", "s1", NOW)
    load_list(conn, h1_2024(), "u1", "s1", NOW)
    assert conn.execute("SELECT count(*) FROM market_cap_rank").fetchone() == (3,)
