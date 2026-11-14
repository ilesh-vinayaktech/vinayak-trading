"""Daily bar completeness: nothing quarantined, no open weekday without bars, no day with far fewer bars than usual."""

from datetime import UTC, date, datetime, timedelta

import pytest

from algo.data.quality.completeness import check
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 6, tzinfo=UTC)
START = date(2026, 9, 1)  # a Tuesday
WEEKDAYS = [
    START + timedelta(days=i) for i in range(40) if (START + timedelta(days=i)).weekday() < 5
]


def ts(d):
    return datetime(d.year, d.month, d.day, 3, 45, tzinfo=UTC)


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    ids = [repo.add_instrument(x, f"S{i}") for i in range(10)]
    return conn, ids


def fill(conn, ids, days, n=10, source="nse"):
    for d in days:
        for iid in ids[:n]:
            conn.execute(
                "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,dataset_version,"
                "ingested_at) VALUES (%s,%s,1,1,1,1,1,%s,1,%s)",
                (iid, ts(d), source, NOW),
            )


def partition(conn, d, status):
    conn.execute(
        "INSERT INTO partition_load (source,dataset,partition,raw_version,checksum,status,at)"
        " VALUES ('nse','bhav',%s,1,'x',%s,%s)",
        (d, status, NOW),
    )


def test_a_complete_history_is_clean(env):
    conn, ids = env
    fill(conn, ids, WEEKDAYS)
    r = check(conn, START)
    assert (r.quarantined, r.missing_days, r.thin_days) == ([], [], [])


def test_a_day_with_far_fewer_bars_than_the_recent_average_is_thin(env):
    conn, ids = env
    thin = WEEKDAYS[25]
    fill(conn, ids, [d for d in WEEKDAYS if d != thin])
    fill(conn, ids, [thin], n=5)  # half the usual
    fill(conn, ids, [WEEKDAYS[26]], n=0)
    r = check(conn, START)
    assert r.thin_days == [(thin, 5, 10)] and r.missing_days == []


def test_an_open_weekday_without_bars_is_missing_unless_it_is_a_marked_holiday(env):
    conn, ids = env
    gap, holiday, closed = WEEKDAYS[10], WEEKDAYS[15], WEEKDAYS[20]
    fill(conn, ids, [d for d in WEEKDAYS if d not in (gap, holiday, closed)])
    partition(conn, holiday, "not_published")
    conn.execute(
        "INSERT INTO market_session (session_date,kind,note,source,created_at)"
        " VALUES (%s,'CLOSED','h','nse',%s)",
        (closed, NOW),
    )
    r = check(conn, START)
    assert r.missing_days == [gap]


def test_a_quarantined_file_stays_listed_until_a_later_load_replaces_it(env):
    conn, ids = env
    fill(conn, ids, WEEKDAYS)
    partition(conn, WEEKDAYS[5], "quarantined")
    partition(conn, WEEKDAYS[6], "quarantined")
    partition(conn, WEEKDAYS[6], "loaded")  # recovered
    assert check(conn, START).quarantined == [WEEKDAYS[5]]
    assert check(conn, WEEKDAYS[-1]).quarantined == [WEEKDAYS[5]]  # not limited to the window


def test_other_sources_and_days_before_the_window_do_not_count(env):
    conn, ids = env
    fill(conn, ids, WEEKDAYS[10:])
    fill(conn, ids, WEEKDAYS[:10], source="kite")  # Kite bars do not make NSE complete
    r = check(conn, WEEKDAYS[10])
    assert r.missing_days == [] and r.thin_days == []
    assert check(conn, START).missing_days == WEEKDAYS[:10]
