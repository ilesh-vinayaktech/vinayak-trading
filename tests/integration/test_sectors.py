# ruff: noqa: E501
from datetime import UTC, date, datetime

import psycopg
import pytest

from algo.data import sectors
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 15, tzinfo=UTC)
HEAD = "Company Name,Industry,Symbol,Series,ISIN Code\n"


def lst(*rows):
    return (
        HEAD
        + "".join(f"{n} Ltd.,{ind},{sym},EQ,INE{k:09d}\n" for k, (n, ind, sym) in enumerate(rows))
    ).encode("utf-8-sig")


def test_a_snapshot_is_stored_by_symbol_a_change_is_a_new_row_and_history_answers_by_date(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    a, b = repo.add_instrument(x, "AAA"), repo.add_instrument(x, "BBB")
    for iid, sym in ((a, "AAA"), (b, "BBB")):
        repo.add_alias(iid, "nse", sym, date(2000, 1, 1))
    d1, d2, d3 = date(2026, 5, 1), date(2026, 8, 1), date(2026, 11, 1)
    assert sectors.load_snapshot(
        conn, lst(("A", "IT", "AAA"), ("B", "Banks", "BBB"), ("Z", "Autos", "ZZZ")), d1, "s1", NOW
    ) == (2, ["ZZZ"])
    assert sectors.load_snapshot(
        conn, lst(("A", "IT", "AAA"), ("B", "Banks", "BBB")), d2, "s2", NOW
    ) == (0, [])  # unchanged: nothing added
    assert sectors.load_snapshot(
        conn, lst(("A", "Software", "AAA"), ("B", "Banks", "BBB")), d3, "s3", NOW
    ) == (1, [])
    assert sectors.sectors_on(conn, d2) == {a: "IT", b: "Banks"}
    assert sectors.sectors_on(conn, d3) == {a: "Software", b: "Banks"}  # AAA changed sector
    assert sectors.sectors_on(conn, date(2026, 1, 1)) == {}  # before any snapshot
    with pytest.raises(psycopg.errors.RaiseException, match="insert-only"):
        conn.execute("UPDATE instrument_sector SET sector='x'")


def test_the_newest_list_in_the_lake_is_loaded_with_its_date_and_hash_and_a_missing_one_is_an_error(
    conn, tmp_path
):
    import hashlib

    migrate(conn)
    repo = InstrumentRepo(conn)
    a = repo.add_instrument(repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE"), "AAA")
    repo.add_alias(a, "nse", "AAA", date(2000, 1, 1))
    with pytest.raises(FileNotFoundError, match="no nifty500_list"):
        sectors.load_latest(conn, tmp_path, NOW)
    base = tmp_path / "raw/niftyindices/nifty500_list"
    (base / "dt=2026-05-01").mkdir(parents=True)
    (base / "dt=2026-05-01/v0001.bin").write_bytes(lst(("A", "Old", "AAA")))
    new = lst(("A", "IT", "AAA"))
    (base / "dt=2026-11-10").mkdir()
    (base / "dt=2026-11-10/v0001.bin").write_bytes(new)
    assert sectors.load_latest(conn, tmp_path, NOW) == (date(2026, 11, 10), 1, [])
    assert conn.execute(
        "SELECT sector, effective_from, source_sha256 FROM instrument_sector"
    ).fetchall() == [("IT", date(2026, 11, 10), hashlib.sha256(new).hexdigest())]
    (base / "dt=2026-11-12").mkdir()
    with pytest.raises(FileNotFoundError, match="holds no list file"):
        sectors.load_latest(conn, tmp_path, NOW)
