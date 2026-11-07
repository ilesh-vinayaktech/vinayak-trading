from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from algo.data.instrument_sync import TERMS_NOTE, sync_equities
from algo.data.providers.nse_security_master import parse_security_master
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
RAW = (Path(__file__).parents[1] / "data/nse/EQUITY_L.csv").read_bytes()
ON = date(2026, 11, 5)


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    return conn, repo, repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")


def test_adds_instruments_with_alias_and_assumed_terms_and_is_idempotent(env):
    conn, repo, x = env
    secs = parse_security_master(RAW)
    r = sync_equities(conn, x, secs, ON)
    assert len(r.added) == 5 and r.missing == []
    iid = repo.resolve("nse", "RELIANCE", ON)
    t = repo.terms_as_of(iid, ON)
    assert (t.lot_size, str(t.tick_size), t.margin_rule_version) == (1, "0.05", TERMS_NOTE)
    row = conn.execute(
        "SELECT isin, name, listed_on FROM instrument WHERE instrument_id=%s", (iid,)
    )
    assert row.fetchone() == ("INE002A01018", "Reliance Industries Limited", date(1995, 11, 29))
    assert sync_equities(conn, x, secs, ON).added == []
    assert conn.execute("SELECT count(*) FROM instrument").fetchone()[0] == 5


def test_missing_symbols_reported_never_delisted(env):
    conn, _, x = env
    secs = parse_security_master(RAW)
    sync_equities(conn, x, secs, ON)
    r = sync_equities(conn, x, [s for s in secs if s.symbol != "TCS"], ON)
    assert r.missing == ["TCS"] and r.added == []
    assert (
        conn.execute("SELECT status FROM instrument WHERE symbol='TCS'").fetchone()[0] == "active"
    )


def test_future_listing_synced_twice_is_idempotent(env):
    """Regression (found on real NSE data): a security listing AFTER the sync date has an alias
    not yet valid on that date; it must still count as known, not be re-added and conflict."""
    conn, _, x = env
    secs = parse_security_master(RAW)
    future = [replace(secs[0], symbol="NEWIPO", isin="INE000000001", listed_on=date(2026, 11, 6))]
    assert sync_equities(conn, x, future, ON).added == ["NEWIPO"]
    r = sync_equities(conn, x, future, ON)
    assert r.added == [] and r.missing == []
