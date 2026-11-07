from datetime import UTC, date, datetime
from decimal import Decimal as D
from pathlib import Path

import psycopg
import pytest

from algo.core.calendar import nse
from algo.data.instrument_sync import sync_equities
from algo.data.lake import LocalLake
from algo.data.pipeline import backfill, run_partition
from algo.data.providers.base import NotPublishedError
from algo.data.providers.nse_bhavcopy import NseBhavcopy
from algo.data.providers.nse_security_master import parse_security_master
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
D0 = date(2026, 11, 5)
NOW = datetime(2026, 11, 5, 13, 0, tzinfo=UTC)
RAW = (Path(__file__).parents[1] / "data/nse/sec_bhavdata_full_05112026.csv").read_bytes()


class Prov(NseBhavcopy):
    def __init__(self):
        self.payload = RAW
        super().__init__(lambda u: self.payload, nse())


@pytest.fixture
def env(conn, tmp_path):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    master = (Path(__file__).parents[1] / "data/nse/EQUITY_L.csv").read_bytes()
    secs = [s for s in parse_security_master(master) if s.symbol != "AGSTRA"]  # AGSTRA unknown
    sync_equities(conn, x, secs, D0)
    ids = {s.symbol: repo.resolve("nse", s.symbol, D0) for s in secs}
    return conn, LocalLake(tmp_path), Prov(), ids


def count(conn, where="true"):
    return conn.execute(f"SELECT count(*) FROM bar_1d WHERE {where}").fetchone()[0]


def test_load_then_rerun_is_noop(env):
    conn, lake, prov, ids = env
    r = run_partition(conn, lake, prov, "bhav", D0, NOW)
    assert (r.status, r.dataset_version, r.rows, r.unknown_symbols) == ("loaded", 1, 4, ["AGSTRA"])
    q = "SELECT ts, close, volume, series, prev_close, delivery_qty FROM bar_1d"
    q += " WHERE instrument_id=%s"
    row = conn.execute(q, (ids["RELIANCE"],)).fetchone()
    assert row == (
        datetime(2026, 11, 5, 3, 45, tzinfo=UTC), D("1313.40"), D("19479324"), "EQ",
        D("1311.00"), D("9060662"),
    )  # fmt: skip
    r2 = run_partition(conn, lake, prov, "bhav", D0, NOW)
    assert r2.status == "noop" and r2.dataset_version == 1 and count(conn) == 4


def test_correction_creates_new_version_and_keeps_old(env):
    conn, lake, prov, ids = env
    run_partition(conn, lake, prov, "bhav", D0, NOW)
    prov.payload = RAW.replace(b"1313.40", b"1314.40")
    r = run_partition(conn, lake, prov, "bhav", D0, NOW, "provider_correction")
    assert r.status == "loaded" and r.dataset_version == 2
    closes = conn.execute(
        "SELECT dataset_version, close FROM bar_1d WHERE instrument_id=%s ORDER BY 1",
        (ids["RELIANCE"],),
    ).fetchall()
    assert closes == [(1, D("1313.40")), (2, D("1314.40"))]


def test_invalid_data_quarantined_never_loaded(env):
    conn, lake, prov, _ = env
    prov.payload = RAW.replace(b"1325.00", b"1000.00")  # high below open/close
    r = run_partition(conn, lake, prov, "bhav", D0, NOW)
    assert r.status == "quarantined" and r.issues and count(conn) == 0
    assert conn.execute("SELECT status FROM partition_load").fetchone()[0] == "quarantined"


def test_parse_error_quarantined(env):
    conn, lake, prov, _ = env
    prov.payload = b"garbage"
    r = run_partition(conn, lake, prov, "bhav", D0, NOW)
    assert r.status == "quarantined" and count(conn) == 0


def test_crash_mid_load_leaves_no_partial_partition(env):
    conn, lake, prov, ids = env
    # make the 2nd instrument's insert fail, after the 1st already succeeded
    only = f"ALTER TABLE bar_1d ADD CONSTRAINT only_one CHECK (instrument_id = {ids['RELIANCE']})"
    conn.execute(only)
    with pytest.raises(psycopg.errors.CheckViolation):
        run_partition(conn, lake, prov, "bhav", D0, NOW)
    assert count(conn) == 0  # first row rolled back with the rest
    loaded = conn.execute("SELECT count(*) FROM partition_load WHERE status='loaded'").fetchone()
    assert loaded[0] == 0


class Flaky(Prov):
    """Provider that has no file on the dates in `missing` (holidays)."""

    def __init__(self, missing):
        super().__init__()
        self.missing = missing
        self.fetched = []

    def fetch(self, dataset, d):
        self.fetched.append(d)
        if d in self.missing:
            raise NotPublishedError(f"no file {d}")
        return self.payload


def test_backfill_records_holidays_skips_weekends_and_is_resumable(env):
    conn, lake, _, _ = env
    prov = Flaky({date(2026, 11, 3)})
    prov.payload = RAW
    # 2026-11-05 Thu .. 2026-11-08 Sun; only 11-05 matches the fixture's date
    seen = []
    out = backfill(conn, lake, prov, "bhav", date(2026, 11, 5), date(2026, 11, 8), NOW,
                   progress=lambda d, st: seen.append((d, st)))  # fmt: skip
    # 11-06 gets the same file back (dated 11-05) => stale holiday file => not_published
    assert out == {"loaded": 1, "not_published": 1} and seen[0] == (date(2026, 11, 5), "loaded")
    assert date(2026, 11, 7) not in prov.fetched  # Saturday never requested
    # holiday recorded, then not fetched again; loaded day not fetched again
    out2 = backfill(conn, lake, prov, "bhav", date(2026, 11, 3), date(2026, 11, 5), NOW)
    # 11-04 quarantines (fixture is dated 11-05) and is retried every run; 11-03 is a recent miss
    assert out2 == {"not_published": 1, "quarantined": 1}
    assert prov.fetched.count(date(2026, 11, 5)) == 1
    out3 = backfill(conn, lake, prov, "bhav", date(2026, 11, 3), date(2026, 11, 5), NOW)
    assert out3 == {"not_published": 1, "quarantined": 1}  # recent miss retried too
    assert prov.fetched.count(date(2026, 11, 3)) == 2
    st = conn.execute(
        "SELECT status, raw_version, checksum FROM partition_load WHERE partition='2026-11-03'"
    ).fetchone()
    assert st == ("not_published", None, None)


def test_backfill_respects_custom_trading_day_predicate(env):
    conn, lake, _, _ = env
    prov = Flaky(set())
    out = backfill(conn, lake, prov, "bhav", date(2026, 11, 4), date(2026, 11, 5), NOW,
                   is_trading_day=lambda d: d == date(2026, 11, 5))  # fmt: skip
    assert out == {"loaded": 1} and prov.fetched == [date(2026, 11, 5)]


def test_recent_not_published_is_retried_old_one_is_final(env):
    """A miss within a week may just be 'not posted yet'; an old miss is a holiday."""
    conn, lake, _, _ = env
    old, recent = date(2026, 10, 12), date(2026, 11, 4)
    prov = Flaky({old, recent})
    for _ in range(2):
        backfill(conn, lake, prov, "bhav", old, old, NOW)
        backfill(conn, lake, prov, "bhav", recent, recent, NOW)
    assert prov.fetched.count(old) == 1  # final after the first miss
    assert prov.fetched.count(recent) == 2  # tried again on the second run


def test_stale_file_on_a_holiday_is_recorded_not_published_and_loads_nothing(env):
    conn, lake, _, _ = env
    prov = Prov()
    prov.payload = RAW.replace(b"05-Nov-2026", b"04-Nov-2026")  # NSE re-served the prior day
    out = backfill(conn, lake, prov, "bhav", D0, D0, NOW)
    assert out == {"not_published": 1} and count(conn) == 0
