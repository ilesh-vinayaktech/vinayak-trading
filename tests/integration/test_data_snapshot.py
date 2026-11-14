"""Named, sealed data snapshots and the DataAPI that serves only what a snapshot pinned."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import psycopg
import pytest

from algo.data import freeze
from algo.data.data_snapshot import DataAPI, NotInSnapshot, SnapshotChanged, create, get, verify
from algo.data.reader import BarReader
from tests.support.bt import DAYS, INGESTED, NOW, flat, make_env, put_bars

pytestmark = pytest.mark.integration
T0 = datetime(2026, 11, 6, 12, tzinfo=UTC)  # after the first load
T1 = datetime(2026, 11, 8, 12, tzinfo=UTC)  # the provider's correction arrives


@pytest.fixture
def env(conn):
    conn, a, b = make_env(conn)
    put_bars(conn, a, flat(100))
    put_bars(conn, b, flat(50))
    return conn, a, b


def correct(conn, iid, price, at=T1):
    for d in DAYS:
        conn.execute(
            "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,dataset_version,ingested_at)"
            " VALUES (%s,%s,%s,%s,%s,%s,10000000,'nse',2,%s)",
            (
                iid,
                datetime(d.year, d.month, d.day, 3, 45, tzinfo=UTC),
                price,
                price,
                price,
                price,
                at,
            ),
        )


def load(conn, day, status="loaded", at=INGESTED):
    conn.execute(
        "INSERT INTO partition_load (source,dataset,partition,raw_version,checksum,status,dataset_version,at)"
        " VALUES ('nse','bhav',%s,1,%s,%s,1,%s)",
        (day, f"sum-{day}", status, at),
    )


def closes(api, iid):
    return [b.close for b in api.history(iid, DAYS[0], DAYS[-1]).bars]


def test_a_sealed_snapshot_records_what_it_pins_and_the_files_behind_the_data(env):
    conn, a, b = env
    load(conn, DAYS[0])
    load(conn, DAYS[1], at=T1)  # loaded after the cutoff: not part of the manifest
    sid = create(conn, NOW, instruments=[b, a], known_at=T0, note="first", code_commit="abc123",
                 pins={"cost_schedule": "zerodha-nse-cash v4"})  # fmt: skip
    s = get(conn, sid)
    assert (s["status"], s["cutoff_time"], s["price_source"], s["price_cutoff"]) == (
        "sealed",
        T0,
        "bhavcopy",
        None,
    )
    assert s["instrument_ids"] == sorted([a, b])
    assert s["snapshot_hash"] == BarReader(conn, known_at=T0).snapshot_hash([a, b])
    assert (
        s["pins"]["code_commit"] == "abc123" and s["pins"]["cost_schedule"] == "zerodha-nse-cash v4"
    )
    assert s["pins"]["freeze"] is None and len(s["pins"]["calendar"]) == 64
    assert [(p["partition_date"], p["checksum"]) for p in s["partitions"]] == [
        (DAYS[0], f"sum-{DAYS[0]}")
    ]
    assert verify(conn, sid) == []


def test_the_data_api_serves_the_pinned_data_after_the_provider_corrects_history(env):
    conn, a, b = env
    sid = create(conn, NOW, instruments=[a, b], known_at=T0, note="n")
    api = DataAPI(conn, sid)
    before = closes(api, a)
    correct(conn, a, 110)  # a new dataset version, ingested after the cutoff
    assert closes(DataAPI(conn, sid), a) == before == [D(100)] * len(DAYS)
    later = create(conn, NOW, instruments=[a, b], known_at=T1 + timedelta(hours=1), note="later")
    assert closes(DataAPI(conn, later), a) == [D(110)] * len(DAYS)
    assert get(conn, later)["snapshot_hash"] != get(conn, sid)["snapshot_hash"]
    assert api.ref() == {"snapshot_id": str(sid), "hash": get(conn, sid)["snapshot_hash"]}


def test_only_the_pinned_instruments_are_served(env):
    conn, a, b = env
    api = DataAPI(conn, create(conn, NOW, instruments=[a], known_at=T0, note="n"))
    assert closes(api, a)
    with pytest.raises(NotInSnapshot):
        api.history(b, DAYS[0], DAYS[-1])


def test_a_snapshot_cannot_be_edited_or_deleted(env):
    conn, a, _ = env
    load(conn, DAYS[0])
    sid = create(conn, NOW, instruments=[a], known_at=T0, note="n")
    for sql in (
        "UPDATE data_snapshot SET note='x' WHERE snapshot_id=%s",
        "DELETE FROM data_snapshot WHERE snapshot_id=%s",
        "DELETE FROM snapshot_partition WHERE snapshot_id=%s",
    ):
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute(sql, (sid,))


def test_data_that_changed_under_a_snapshot_is_found_and_refused(env):
    conn, a, b = env
    sid = create(conn, NOW, instruments=[a, b], known_at=T0, note="n")
    conn.execute(
        "DELETE FROM bar_1d WHERE instrument_id=%s AND ts<%s", (b, datetime(2025, 6, 4, tzinfo=UTC))
    )
    problems = verify(conn, sid)
    assert len(problems) == 1 and "bars, actions or decisions" in problems[0]
    with pytest.raises(SnapshotChanged, match="changed"):
        DataAPI(conn, sid)
    assert DataAPI(conn, sid, verify=False).instruments == sorted(
        [a, b]
    )  # explicit, for inspection


def test_the_calendar_is_pinned_too(env):
    conn, a, _ = env
    sid = create(conn, NOW, instruments=[a], known_at=T0, note="n")
    conn.execute(
        "INSERT INTO market_session (session_date,kind,note,source,created_at) VALUES ('2025-06-05','CLOSED','h','nse',%s)",
        (INGESTED,),
    )  # a holiday that was entered with a date before the cutoff changes what the calendar was
    assert any("calendar" in p for p in verify(conn, sid))


def test_the_kite_freeze_in_force_is_recorded_and_a_stitched_snapshot_keeps_its_cutoff(env):
    conn, a, _ = env
    conn.execute(
        "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,adjusted_through,dataset_version,ingested_at)"
        " VALUES (%s,%s,1,1,1,1,1,'kite',%s,1,%s)",
        (a, datetime(2025, 6, 2, 3, 45, tzinfo=UTC), date(2026, 11, 1), INGESTED),
    )
    fid = freeze.take(conn, "kite", date(2025, 6, 2), datetime(2026, 11, 6, 6, tzinfo=UTC), "n")
    sid = create(
        conn,
        NOW,
        instruments=[a],
        known_at=T0,
        price_source="bhavcopy",
        price_cutoff=DAYS[3],
        note="n",
    )
    s = get(conn, sid)
    assert (
        s["pins"]["freeze"] == {"id": str(fid), "through": "2025-06-02"}
        and s["price_cutoff"] == DAYS[3]
    )
    assert DataAPI(conn, sid).reader.cutoff == DAYS[3]


def test_a_kite_snapshot_reads_through_the_kite_reader(env):
    conn, a, _ = env
    sid = create(conn, NOW, instruments=[a], known_at=T0, price_source="kite", note="n")
    assert DataAPI(conn, sid).reader.source == "kite"
    with pytest.raises(ValueError, match="price_source"):
        create(conn, NOW, instruments=[a], price_source="yahoo", note="n")
    with pytest.raises(ValueError, match="price_cutoff"):
        create(conn, NOW, instruments=[a], price_source="kite", price_cutoff=DAYS[0], note="n")
    with pytest.raises(ValueError, match="instruments"):
        create(conn, NOW, instruments=[], note="n")
    with pytest.raises(ValueError, match="note"):
        create(conn, NOW, instruments=[a], note=" ")
