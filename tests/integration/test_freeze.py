"""Freezing a price source's history: record exactly what it holds, prove later that it is unchanged, and refuse to add to it."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from algo.data import freeze
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)
D0 = date(2026, 11, 2)
THROUGH = date(2026, 11, 4)


def ts(d):
    return datetime(d.year, d.month, d.day, 3, 45, tzinfo=UTC)


def put(conn, iid, day, close, source="kite"):
    conn.execute(
        "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,adjusted_through,dataset_version,ingested_at)"
        " VALUES (%s,%s,1,9,1,%s,100,%s,%s,1,%s)",
        (iid, ts(day), close, source, date(2026, 11, 11) if source == "kite" else None, NOW),
    )


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    a, b, c = (repo.add_instrument(x, s) for s in ("AAA", "BBB", "CCC"))
    for i in range(5):  # 2026-11-02 .. 11-06: two days after the freeze date
        put(conn, a, D0 + timedelta(days=i), 10 + i)
        put(conn, b, D0 + timedelta(days=i), 20 + i)
        put(
            conn, a, D0 + timedelta(days=i), 99 + i, source="nse"
        )  # another source is never part of a Kite freeze
    return conn, a, b, c


def test_a_freeze_records_each_stocks_rows_up_to_the_date_and_nothing_after(env):
    conn, a, b, _ = env
    fid = freeze.take(conn, "kite", THROUGH, NOW, "first frozen copy")
    f = freeze.get(conn, fid)
    assert (f["source"], f["dataset"], f["through_date"], f["instruments"], f["total_rows"]) == (
        "kite", "bar_1d", THROUGH, 2, 6,
    )  # fmt: skip
    assert f["note"] == "first frozen copy" and f["taken_at"] == NOW
    items = {i["instrument_id"]: i for i in f["items"]}
    assert (
        set(items) == {a, b} and items[a]["row_count"] == 3
    )  # 11-02, 11-03, 11-04: not 11-05, 11-06
    assert (items[a]["first_ts"], items[a]["last_ts"]) == (ts(D0), ts(THROUGH))
    assert len(items[a]["sha256"]) == 64 and items[a]["sha256"] != items[b]["sha256"]


def test_a_clean_history_verifies_and_a_changed_or_missing_row_is_named_by_stock(env):
    conn, a, b, _ = env
    fid = freeze.take(conn, "kite", THROUGH, NOW, "n")
    assert freeze.verify(conn, fid) == []
    put(conn, a, date(2026, 11, 9), 50)  # a NEW later day does not touch the frozen part
    assert freeze.verify(conn, fid) == []
    conn.execute(
        "UPDATE bar_1d SET close=777 WHERE instrument_id=%s AND ts=%s AND source='kite'",
        (a, ts(D0)),
    )
    conn.execute(
        "DELETE FROM bar_1d WHERE instrument_id=%s AND ts=%s AND source='kite'", (b, ts(THROUGH))
    )
    problems = {p["instrument_id"]: p for p in freeze.verify(conn, fid)}
    assert set(problems) == {a, b}
    assert (
        problems[a]["why"] == "rows changed" and problems[b]["why"] == "3 rows were frozen, 2 now"
    )


def test_a_stock_that_disappeared_entirely_is_reported_too(env):
    conn, a, _, _ = env
    fid = freeze.take(conn, "kite", THROUGH, NOW, "n")
    conn.execute("DELETE FROM bar_1d WHERE instrument_id=%s AND source='kite'", (a,))
    assert [(p["instrument_id"], p["why"]) for p in freeze.verify(conn, fid)] == [
        (a, "3 rows were frozen, 0 now")
    ]


def test_the_same_source_and_date_cannot_be_frozen_twice_and_an_empty_freeze_is_refused(env):
    conn, _, _, _ = env
    freeze.take(conn, "kite", THROUGH, NOW, "n")
    with pytest.raises(freeze.FreezeError, match="already frozen"):
        freeze.take(conn, "kite", THROUGH, NOW, "again")
    with pytest.raises(freeze.FreezeError, match="no kite bars"):
        freeze.take(conn, "kite", date(2020, 1, 1), NOW, "before any data")
    with pytest.raises(freeze.FreezeError, match="in the future"):
        freeze.take(conn, "kite", date(2030, 1, 1), NOW, "tomorrow")
    with pytest.raises(freeze.FreezeError, match="note"):
        freeze.take(conn, "kite", date(2026, 11, 3), NOW, "  ")
    with pytest.raises(freeze.FreezeError, match="no such freeze"):
        freeze.verify(conn, uuid4())
    assert freeze.get(conn, uuid4()) is None


def test_the_record_itself_cannot_be_edited_or_deleted(env):
    conn, _, _, _ = env
    fid = freeze.take(conn, "kite", THROUGH, NOW, "n")
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        conn.execute("UPDATE data_freeze SET note='x' WHERE freeze_id=%s", (fid,))
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        conn.execute("DELETE FROM data_freeze_item WHERE freeze_id=%s", (fid,))


def test_the_guard_refuses_new_frozen_history_but_not_later_days_other_stocks_or_other_sources(env):
    conn, a, b, c = env
    freeze.take(conn, "kite", THROUGH, NOW, "n")
    conn.execute(
        "DELETE FROM bar_1d WHERE instrument_id=%s AND ts=%s AND source='kite'", (a, ts(D0))
    )  # a gap in frozen history
    with pytest.raises(psycopg.errors.RaiseException, match="frozen"):
        put(conn, a, D0, 10)  # refilling it would change frozen history
    put(conn, a, date(2026, 11, 10), 15)  # after the freeze date: fine
    put(conn, c, D0, 30)  # a stock that was not in the freeze: fine
    put(conn, b, D0 - timedelta(days=30), 5, source="nse")  # another source: fine
    with conn.transaction():  # a deliberate, explicit gap fill
        conn.execute("SELECT set_config('algo.allow_frozen_write', 'on', true)")
        put(conn, a, D0, 10)
    assert conn.execute(
        "SELECT count(*) FROM bar_1d WHERE instrument_id=%s AND source='kite'", (a,)
    ).fetchone() == (6,)  # 4 original + the later day + the refilled gap
