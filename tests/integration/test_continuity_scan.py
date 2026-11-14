"""Daily price-continuity scan on the raw NSE closes: a jump nobody recorded is an alert."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from algo.data.corporate_actions import knowledge_time_for
from algo.data.quality.continuity_scan import scan
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
INGESTED = datetime(2026, 11, 6, tzinfo=UTC)
D0 = date(2026, 10, 26)  # Monday
SINCE = date(2026, 10, 29)


def ts(d):
    return datetime(d.year, d.month, d.day, 3, 45, tzinfo=UTC)


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    ids = {}
    for s in ("FLAT", "JUMP", "SPLIT", "PENDING", "GAPPED", "OLDJUMP"):
        ids[s] = repo.add_instrument(x, s)
        repo.add_alias(ids[s], "nse", s, date(2000, 1, 1))
    return conn, ids


def bars(conn, iid, closes, start=D0, source="nse"):
    for i, c in enumerate(closes):
        conn.execute(
            "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,dataset_version,"
            "ingested_at) VALUES (%s,%s,%s,%s,%s,%s,100,%s,1,%s)",
            (iid, ts(start + timedelta(days=i)), c, c, c, c, source, INGESTED),
        )


def action(conn, iid, ex, kind, status, num=None, den=None):
    conn.execute(
        "INSERT INTO corporate_action (instrument_id,ex_date,kind,status,num,den,subject,"
        "knowledge_time,knowledge_time_source,source,raw_checksum,ingested_at) VALUES"
        " (%s,%s,%s,%s,%s,%s,'t',%s,'ex_date_proxy','nse','x',%s)",
        (iid, ex, kind, status, num, den, knowledge_time_for(ex), INGESTED),
    )


def test_only_a_jump_with_no_recorded_action_is_unexplained(env):
    conn, ids = env
    bars(conn, ids["FLAT"], [100, 101, 102, 101, 100, 101, 102])
    bars(conn, ids["JUMP"], [100, 101, 102, 101, 40, 41, 42])  # -60% on 10-30, nothing recorded
    bars(conn, ids["SPLIT"], [100, 101, 102, 101, 50, 51, 52])  # a 2:1 bonus explains it
    action(conn, ids["SPLIT"], D0 + timedelta(days=4), "bonus", "ok", D(2), D(1))
    bars(conn, ids["PENDING"], [100, 101, 102, 101, 60, 61, 62])  # a demerger waiting for a person
    action(conn, ids["PENDING"], D0 + timedelta(days=4), "demerger", "review")
    r = scan(conn, SINCE)
    assert r.scanned == 4
    assert [(f.symbol, f.day, f.kind) for f in r.unexplained] == [
        ("JUMP", D0 + timedelta(days=4), "unexplained_jump")
    ]
    assert [(f.symbol, f.day) for f in r.pending] == [("PENDING", D0 + timedelta(days=4))]


def test_a_recorded_action_that_the_price_did_not_follow_is_reported(env):
    conn, ids = env
    bars(conn, ids["SPLIT"], [100, 101, 102, 101, 100, 101, 102])  # a 10:1 split but no price move
    action(conn, ids["SPLIT"], D0 + timedelta(days=4), "split", "ok", D(10), D(1))
    (f,) = scan(conn, SINCE).unexplained
    assert (f.symbol, f.kind) == ("SPLIT", "action_without_discontinuity")


def test_a_long_trading_gap_and_old_history_are_not_alerts(env):
    conn, ids = env
    bars(conn, ids["GAPPED"], [100, 101])  # then nothing for 9 days, then a very different price
    bars(conn, ids["GAPPED"], [10, 11], start=D0 + timedelta(days=11))
    bars(conn, ids["OLDJUMP"], [100, 40, 41, 42, 43, 44, 45])  # the jump is before SINCE
    r = scan(conn, date(2026, 10, 30))
    assert r.unexplained == [] and r.pending == []


def test_other_sources_do_not_count(env):
    conn, ids = env
    bars(
        conn, ids["JUMP"], [100, 40], source="kite"
    )  # Kite's adjusted candles are not the NSE raw series
    bars(conn, ids["FLAT"], [100, 100])
    r = scan(conn, D0)
    assert r.scanned == 1 and r.unexplained == []


def pair(conn, iid, a, b, close_a=100, close_b=160):
    bars(conn, iid, [close_a], start=a)
    bars(conn, iid, [close_b], start=b)


def test_a_jump_across_a_session_that_has_no_nse_bars_is_pending_not_an_alert(env):
    conn, ids = env
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XBOM", "IN", "Asia/Kolkata", "INR", "BSE")
    other = repo.add_instrument(x, "OTHER")
    # control: Friday -> Monday, nothing in between but a weekend: a real jump
    pair(conn, ids["FLAT"], date(2026, 10, 2), date(2026, 10, 5))
    # a Kite bar on the Sunday in between (the Muhurat session NSE's file does not carry)
    pair(conn, ids["JUMP"], date(2026, 10, 9), date(2026, 10, 12))
    bars(conn, other, [50], start=date(2026, 10, 11), source="kite")
    # a calendar SESSION entry on the Saturday in between
    pair(conn, ids["SPLIT"], date(2026, 10, 16), date(2026, 10, 19))
    conn.execute(
        "INSERT INTO market_session (session_date,kind,start_time,end_time,note,source,created_at)"
        " VALUES ('2026-10-17','SESSION','18:00','19:00','muhurat','manual',%s)",
        (INGESTED,),
    )
    # an open weekday (Wednesday) on which NSE published nothing at all
    pair(conn, ids["PENDING"], date(2026, 10, 20), date(2026, 10, 22))
    r = scan(conn, date(2026, 10, 1))
    assert [(f.symbol, f.day) for f in r.unexplained] == [("FLAT", date(2026, 10, 5))]
    assert sorted((f.symbol, f.day) for f in r.pending) == [
        ("JUMP", date(2026, 10, 12)),
        ("PENDING", date(2026, 10, 22)),
        ("SPLIT", date(2026, 10, 19)),
    ]
    assert {f.detail.split(";")[-1].strip() for f in r.pending} == {
        "spans a session without NSE bars"
    }


def test_a_closed_weekday_in_between_is_not_a_missing_session(env):
    conn, ids = env
    pair(conn, ids["FLAT"], date(2026, 10, 20), date(2026, 10, 22))
    conn.execute(
        "INSERT INTO market_session (session_date,kind,note,source,created_at)"
        " VALUES ('2026-10-21','CLOSED','holiday','nse',%s)",
        (INGESTED,),
    )
    (f,) = scan(conn, date(2026, 10, 1)).unexplained
    assert (f.symbol, f.day) == ("FLAT", date(2026, 10, 22))


def test_a_weekday_nse_did_not_publish_a_file_for_is_a_holiday_not_a_missing_session(env):
    conn, ids = env
    pair(conn, ids["FLAT"], date(2026, 10, 20), date(2026, 10, 22))
    conn.execute(
        "INSERT INTO partition_load (source,dataset,partition,status,at)"
        " VALUES ('nse','bhav','2026-10-21','not_published',%s)",
        (INGESTED,),
    )
    (f,) = scan(conn, date(2026, 10, 1)).unexplained  # a real jump across a holiday still alerts
    assert (f.symbol, f.day) == ("FLAT", date(2026, 10, 22))
