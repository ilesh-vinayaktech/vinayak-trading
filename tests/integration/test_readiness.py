"""ReadinessService: may a strategy decide on `day`? Each failing condition blocks on its own."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from algo.data.reader import BarReader
from algo.data.readiness import Needs, assess
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 6, tzinfo=UTC)
WEEKDAYS = [
    date(2026, 9, 1) + timedelta(days=i)
    for i in range(60)
    if (date(2026, 9, 1) + timedelta(days=i)).weekday() < 5
]
DAY = WEEKDAYS[-1]


def ts(d):
    return datetime(d.year, d.month, d.day, 3, 45, tzinfo=UTC)


@pytest.fixture(autouse=True)
def bhavcopy(monkeypatch):
    monkeypatch.setenv("ALGO_PRICE_SOURCE", "bhavcopy")
    monkeypatch.delenv("ALGO_PRICE_CUTOFF", raising=False)


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    ids = []
    for k in range(3):
        iid = repo.add_instrument(x, f"S{k}")
        repo.add_alias(iid, "nse", f"S{k}", date(2000, 1, 1))
        ids.append(iid)
    return conn, ids


def bars(conn, iid, days, source="nse"):
    for d in days:
        conn.execute(
            "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,dataset_version,"
            "ingested_at) VALUES (%s,%s,10,10,10,10,100,%s,1,%s)",
            (iid, ts(d), source, NOW),
        )


def full(conn, ids, days=WEEKDAYS):
    for iid in ids:
        bars(conn, iid, days)


def codes(r):
    return [x.code for x in r.reasons]


def test_complete_fresh_data_is_ready(env):
    conn, ids = env
    full(conn, ids)
    r = assess(conn, Needs(DAY, tuple(ids), warmup_bars=20))
    assert r.ready and r.reasons == [] and r.unready == []


def test_a_decision_day_with_no_bars_yet_is_stale_and_the_allowed_lag_is_exact(env):
    conn, ids = env
    full(conn, ids, WEEKDAYS[:-2])  # the newest bar is two sessions before DAY
    assert codes(assess(conn, Needs(DAY))) == ["STALE"]
    assert codes(assess(conn, Needs(DAY, max_sessions_behind=1))) == [
        "STALE"
    ]  # 2 behind, 1 allowed
    assert assess(conn, Needs(DAY, max_sessions_behind=2)).ready  # exactly at the limit
    full(conn, ids, [WEEKDAYS[-2]])
    assert assess(conn, Needs(DAY, max_sessions_behind=1)).ready  # 1 behind, 1 allowed
    assert codes(assess(conn, Needs(DAY))) == ["STALE"]


def test_a_holiday_is_not_a_session_behind(env):
    conn, ids = env
    full(conn, ids, WEEKDAYS[:-2])
    holiday = WEEKDAYS[-2]
    conn.execute(
        "INSERT INTO partition_load (source,dataset,partition,raw_version,checksum,status,at)"
        " VALUES ('nse','bhav',%s,1,'x','not_published',%s)",
        (holiday, NOW),
    )
    assert assess(conn, Needs(DAY, max_sessions_behind=1)).ready  # only DAY itself is behind


def test_no_bars_at_all_is_not_ready(env):
    conn, _ = env
    assert codes(assess(conn, Needs(DAY))) == ["NO_DATA"]


def test_a_strategy_expecting_another_price_source_is_blocked(env, monkeypatch):
    conn, ids = env
    full(conn, ids)
    assert assess(conn, Needs(DAY, expected_source="bhavcopy")).ready
    (r,) = assess(conn, Needs(DAY, expected_source="kite")).reasons
    assert r.code == "PROVIDER" and "bhavcopy" in r.detail


def test_a_quarantined_file_a_missing_weekday_and_a_thin_day_each_block(env):
    conn, ids = env
    gap = WEEKDAYS[-10]
    full(conn, ids, [d for d in WEEKDAYS if d != gap])
    assert codes(assess(conn, Needs(DAY))) == ["MISSING_DAY"]
    full(conn, ids, [gap])
    conn.execute(
        "INSERT INTO partition_load (source,dataset,partition,raw_version,checksum,status,at)"
        " VALUES ('nse','bhav',%s,1,'x','quarantined',%s)",
        (WEEKDAYS[-5], NOW),
    )
    assert codes(assess(conn, Needs(DAY))) == ["QUARANTINED"]
    assert assess(conn, Needs(DAY, window_days=3)).reasons[0].code == "QUARANTINED"
    thin_day = WEEKDAYS[-3]
    conn.execute("DELETE FROM partition_load")
    conn.execute(
        "DELETE FROM bar_1d WHERE ts=%s AND instrument_id=ANY(%s)", (ts(thin_day), ids[:2])
    )
    assert codes(assess(conn, Needs(DAY))) == ["THIN_DAY"]


def test_instrument_problems_are_listed_and_a_low_share_of_ready_ones_blocks(env):
    conn, ids = env
    a, b, c = ids
    bars(conn, a, WEEKDAYS)
    bars(conn, b, WEEKDAYS[:-1])  # no bar on DAY
    bars(conn, c, WEEKDAYS[-5:])  # only five sessions of history
    r = assess(conn, Needs(DAY, (a, b, c, 999999), warmup_bars=20, min_coverage=D("0.2")))
    assert r.ready
    assert sorted((u.code, u.instrument_id) for u in r.unready) == sorted(
        [("NO_BAR", b), ("SHORT_HISTORY", c), ("UNKNOWN_INSTRUMENT", 999999)]
    )
    strict = assess(conn, Needs(DAY, (a, b, c, 999999), warmup_bars=20))  # 1 of 4 ready < 95%
    assert codes(strict) == ["COVERAGE"] and not strict.ready


def test_a_missing_bar_is_absent_not_a_zero_return(env):
    conn, ids = env
    bars(conn, ids[0], WEEKDAYS)
    bars(conn, ids[1], [d for d in WEEKDAYS if d != DAY])
    r = assess(conn, Needs(DAY, (ids[1],), min_coverage=D("0")))
    assert [u.code for u in r.unready] == ["NO_BAR"]
    h = BarReader(conn).history(ids[1], WEEKDAYS[-3], DAY)
    assert DAY not in [b.ts.date() for b in h.bars]  # nothing was invented for the missing day
