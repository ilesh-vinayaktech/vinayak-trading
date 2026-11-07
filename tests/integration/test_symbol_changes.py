from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from algo.data.instrument_sync import apply_symbol_changes, load_index_snapshot, sync_equities
from algo.data.providers.nse_security_master import Security
from algo.data.providers.nse_symbol_changes import parse_index_list, parse_symbol_changes
from algo.data.store.instruments import InstrumentRepo, NotFoundError
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
DATA = Path(__file__).parents[1] / "data/nse"
CHANGES = parse_symbol_changes((DATA / "symbolchange_sample.csv").read_bytes())
ON = date(2026, 11, 5)


def sec(symbol, listed):
    return Security(symbol, symbol, "EQ", listed, D(1), "INE" + symbol[:6].ljust(6, "0") + "01")


@pytest.fixture
def env(conn):
    migrate(conn)
    x = InstrumentRepo(conn).add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    # today's master lists only CURRENT symbols, each with the company's original listing date
    secs = [sec("TMPV", date(1998, 8, 1)), sec("ETERNAL", date(2021, 7, 23)),
            sec("RELIANCE", date(1995, 11, 29))]  # fmt: skip
    sync_equities(conn, x, secs, ON)
    return conn, InstrumentRepo(conn)


def test_chain_gives_one_continuous_history(env):
    conn, repo = env
    res = apply_symbol_changes(conn, CHANGES)
    assert sorted(res.applied) == ["TATAMOTORS->TMPV", "TELCO->TATAMOTORS", "ZOMATO->ETERNAL"]
    assert res.conflicts == [] and res.not_in_universe == 4  # ADANI*, MCDOWELL, MF row
    tmpv = repo.resolve("nse", "TMPV", ON)
    assert repo.resolve("nse", "TATAMOTORS", date(2020, 1, 1)) == tmpv
    assert repo.resolve("nse", "TELCO", date(2001, 1, 1)) == tmpv
    assert repo.resolve("nse", "TMPV", date(2025, 10, 24)) == tmpv
    assert repo.resolve("nse", "ETERNAL", date(2025, 4, 9)) == repo.resolve(
        "nse", "ZOMATO", date(2025, 4, 8)
    )
    with pytest.raises(NotFoundError):
        repo.resolve("nse", "TATAMOTORS", date(2025, 10, 24))  # renamed that day
    with pytest.raises(NotFoundError):
        repo.resolve("nse", "TELCO", date(2003, 12, 26))
    with pytest.raises(NotFoundError):
        repo.resolve("nse", "TELCO", date(1995, 1, 1))  # before the company listed


def test_apply_twice_is_idempotent(env):
    conn, _ = env
    apply_symbol_changes(conn, CHANGES)
    again = apply_symbol_changes(conn, CHANGES)
    assert again.applied == [] and sorted(again.unchanged) == [
        "TATAMOTORS->TMPV", "TELCO->TATAMOTORS", "ZOMATO->ETERNAL"
    ]  # fmt: skip
    assert conn.execute("SELECT count(*) FROM instrument_alias").fetchone()[0] == 3 + 3


def test_sync_after_renames_adds_nothing_and_reports_nothing_missing(env):
    conn, _ = env
    apply_symbol_changes(conn, CHANGES)
    x = conn.execute("SELECT exchange_id FROM exchange").fetchone()[0]
    secs = [sec("TMPV", date(1998, 8, 1)), sec("ETERNAL", date(2021, 7, 23)),
            sec("RELIANCE", date(1995, 11, 29))]  # fmt: skip
    r = sync_equities(conn, x, secs, ON)
    assert r.added == [] and r.missing == []


def test_symbol_reused_by_another_company_is_a_conflict_not_a_crash(env):
    conn, repo = env
    x = conn.execute("SELECT exchange_id FROM exchange").fetchone()[0]
    other = repo.add_instrument(x, "ZOMATO")
    repo.add_alias(other, "nse", "ZOMATO", date(2020, 1, 1))  # someone else already holds it
    res = apply_symbol_changes(conn, CHANGES)
    assert "ZOMATO->ETERNAL" in res.conflicts
    assert "TELCO->TATAMOTORS" in res.applied  # the rest still go through


def test_index_snapshot_by_symbol_idempotent_and_reports_unknown(env):
    conn, _ = env
    syms = [m.symbol for m in parse_index_list((DATA / "ind_nifty200list_sample.csv").read_bytes())]
    stored, unknown = load_index_snapshot(conn, "NIFTY200", ON, syms)
    assert stored == 3 and unknown == ["ADANIENT", "BAJFINANCE", "TCS"]
    assert load_index_snapshot(conn, "NIFTY200", ON, syms)[0] == 0
