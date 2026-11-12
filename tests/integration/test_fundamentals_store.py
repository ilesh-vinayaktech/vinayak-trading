from datetime import UTC, date, datetime
from decimal import Decimal as D
from pathlib import Path

import pytest

from algo.data.fundamentals import (
    FilingMismatch,
    growth_rows,
    load_quarter_rows,
    note_unloaded,
    store_filing,
)
from algo.data.providers.nse_results import parse_listing, parse_xbrl
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
DATA = Path(__file__).parents[1] / "data/nse"
NOW = datetime(2026, 11, 10, tzinfo=UTC)


def reliance():
    fs = parse_listing((DATA / "results_listing_RELIANCE.json").read_bytes())
    cons = next(f for f in fs if f.period_end == date(2024, 12, 31) and f.basis == "CONSOLIDATED")
    return cons, parse_xbrl((DATA / "results_xbrl_RELIANCE_cons.xml").read_bytes()), fs


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    iid = repo.add_instrument(x, "RELIANCE", isin="INE002A01018")
    return conn, iid


def test_a_filing_and_its_facts_are_stored_once_and_read_back_as_quarter_rows(env):
    conn, iid = env
    f, st, _ = reliance()
    assert store_filing(conn, f, st, "ab" * 32, iid, NOW) is True
    assert store_filing(conn, f, st, "ab" * 32, iid, NOW) is False  # idempotent
    row = conn.execute(
        "SELECT symbol, isin, instrument_id, period_end, basis, audited, bank, filed_at, rounding, raw_sha256 FROM fundamental_filing"
    ).fetchone()
    assert row == (
        "RELIANCE",
        "INE002A01018",
        iid,
        date(2024, 12, 31),
        "CONSOLIDATED",
        False,
        False,
        datetime(2025, 1, 16, 14, 45, 20, tzinfo=UTC),
        "Crores",
        "ab" * 32,
    )
    assert (
        conn.execute(
            "SELECT count(*) FROM fundamental_fact WHERE scope='YTD' AND metric !~ '^[A-Z]'"
        ).fetchone()[0]
        == len(st.ytd)
        > 0
    )
    (qr,) = load_quarter_rows(conn)
    assert (qr.symbol, qr.basis, qr.period_end, qr.metrics["revenue"], qr.metrics["pat"]) == (
        "RELIANCE",
        "CONSOLIDATED",
        date(2024, 12, 31),
        D("2438650000000.00"),
        D("219300000000.00"),
    )
    assert growth_rows([qr])[0].qoq == {}  # a lone quarter has nothing to compare with


def test_a_filing_whose_xbrl_disagrees_with_its_listing_is_refused_and_nothing_is_stored(env):
    conn, iid = env
    f, st, fs = reliance()
    standalone = next(
        x for x in fs if x.period_end == date(2024, 12, 31) and x.basis == "STANDALONE"
    )
    with pytest.raises(FilingMismatch, match="listing says"):
        store_filing(
            conn, standalone, st, "cd" * 32, iid, NOW
        )  # a standalone listing with a consolidated statement
    assert conn.execute("SELECT count(*) FROM fundamental_filing").fetchone()[0] == 0


def test_an_unmapped_isin_still_stores_with_no_instrument_and_unloaded_filings_are_noted_then_cleared(
    env,
):
    conn, _ = env
    f, st, fs = reliance()
    old = next(x for x in fs if x.period_end == date(2017, 12, 31) and x.basis == "CONSOLIDATED")
    note_unloaded(conn, old, "NO_XBRL_OLD_FORMAT", "pre-2018 filing", NOW)
    note_unloaded(
        conn, old, "FETCH_FAILED", "retry", NOW
    )  # a later note replaces the earlier reason
    assert conn.execute(
        "SELECT reason, detail, detail_url IS NOT NULL FROM fundamental_unloaded"
    ).fetchall() == [("FETCH_FAILED", "retry", True)]
    note_unloaded(conn, f, "FETCH_FAILED", "network", NOW)
    assert store_filing(conn, f, st, "ef" * 32, None, NOW) is True  # no instrument for this ISIN
    assert conn.execute("SELECT instrument_id FROM fundamental_filing").fetchone() == (None,)
    assert conn.execute("SELECT seq_number FROM fundamental_unloaded").fetchall() == [
        (old.seq_number,)
    ]  # the stored one is cleared


def test_a_filing_with_no_filing_time_is_refused_by_the_store(env):
    conn, iid = env
    f, st, _ = reliance()
    from dataclasses import replace

    with pytest.raises(FilingMismatch, match="no exact filing time"):
        store_filing(conn, replace(f, filed_at=None), st, "ab" * 32, iid, NOW)
    assert conn.execute("SELECT count(*) FROM fundamental_filing").fetchone()[0] == 0
