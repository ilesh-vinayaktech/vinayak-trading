# ruff: noqa: E501
from datetime import UTC, date, datetime
from decimal import Decimal as D

import pytest

from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
INGESTED = datetime(2026, 11, 6, tzinfo=UTC)


def put(conn, iid, day, close, source, version=1):
    conn.execute(
        "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,dataset_version,ingested_at) VALUES (%s,%s,%s,%s,%s,%s,1000,%s,%s,%s)",
        (
            iid,
            datetime(day.year, day.month, day.day, 3, 45, tzinfo=UTC),
            close,
            close,
            close,
            close,
            source,
            version,
            INGESTED,
        ),
    )


def canon(conn, iid):
    return {
        r[0].date(): (r[1], r[2], r[3])
        for r in conn.execute(
            "SELECT ts, close, source, dataset_version FROM bar_canonical WHERE instrument_id=%s ORDER BY ts",
            (iid,),
        )
    }


def test_the_preferred_source_wins_a_missing_day_falls_back_and_a_correction_supersedes(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    iid = repo.add_instrument(repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE"), "AAA")
    d1, d2, d3, d4 = (date(2026, 11, d) for d in (2, 3, 4, 5))
    put(conn, iid, d1, 100, "kite")
    put(conn, iid, d1, 101, "nse")  # both sources: kite wins
    put(conn, iid, d2, 200, "nse")  # kite lacks the day: nse is the fallback
    put(conn, iid, d3, 300, "nse", 1)
    put(conn, iid, d3, 305, "nse", 2)  # a correction: the newer dataset_version wins
    put(conn, iid, d4, 400, "kite", 1)
    put(conn, iid, d4, 410, "kite", 2)
    got = canon(conn, iid)
    assert got == {
        d1: (D("100"), "kite", 1),
        d2: (D("200"), "nse", 1),
        d3: (D("305"), "nse", 2),
        d4: (D("410"), "kite", 2),
    }
    assert (
        conn.execute("SELECT count(*) FROM bar_1d WHERE instrument_id=%s", (iid,)).fetchone()[0]
        == 7
    )  # the view hides rows, it deletes none


def test_an_instrument_without_bars_has_no_rows_and_nothing_is_invented_for_a_gap(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    a, b = repo.add_instrument(x, "AAA"), repo.add_instrument(x, "BBB")
    put(conn, a, date(2026, 11, 2), 10, "nse")
    put(conn, a, date(2026, 11, 4), 11, "nse")
    assert canon(conn, b) == {} and sorted(canon(conn, a)) == [
        date(2026, 11, 2),
        date(2026, 11, 4),
    ]  # no row for the 3rd
