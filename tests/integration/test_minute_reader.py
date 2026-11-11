from datetime import UTC, date, datetime
from decimal import Decimal as D

import pytest

from algo.data.corporate_actions import knowledge_time_for
from algo.data.minute_reader import minute_history
from algo.data.reader import UnadjustableError
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
INGESTED = datetime(2026, 11, 6, tzinfo=UTC)


def ts(d, minute=0):  # 09:15 IST = 03:45 UTC
    return datetime(d.year, d.month, d.day, 3, 45 + minute, tzinfo=UTC)


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    return conn, repo.add_instrument(x, "XYZ")


def bar(conn, iid, d, close, through, *, volume=D(100), version=1, source="kite"):
    conn.execute(
        "INSERT INTO bar_1m (instrument_id,ts,open,high,low,close,volume,source,adjusted_through,"
        "dataset_version,ingested_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (iid, ts(d), close, close, close, close, volume, source, through, version, INGESTED),
    )


def action(conn, iid, ex, kind, status="ok", num=None, den=None):
    conn.execute(
        "INSERT INTO corporate_action (instrument_id,ex_date,kind,status,num,den,amount,subject,"
        "knowledge_time,knowledge_time_source,source,raw_checksum,ingested_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,NULL,'t',%s,'ex_date_proxy','nse','x',%s)",
        (iid, ex, kind, status, num, den, knowledge_time_for(ex), INGESTED),
    )


D1, D2 = date(2025, 6, 9), date(2025, 6, 13)


def test_none_returns_the_stored_values_and_picks_the_latest_dataset_version(env):
    conn, iid = env
    bar(conn, iid, D1, D(500), date(2026, 11, 1))
    bar(conn, iid, D1, D(501), date(2026, 11, 1), version=2)
    bar(conn, iid, D1, D(9), date(2026, 11, 1), source="other")
    h = minute_history(conn, iid, D1, D1)
    assert [(b.close, b.factor) for b in h.bars] == [(D(501), 1)]
    assert minute_history(conn, iid, D2, D2).bars == []
    with pytest.raises(ValueError):
        minute_history(conn, iid, D1, D1, adjust="total_return")


def test_a_split_already_in_the_vendor_basis_is_not_applied_twice_but_a_later_one_is(env):
    conn, iid = env
    action(conn, iid, date(2025, 6, 12), "bonus", num=D(2), den=D(1))  # x0.5, before the basis day
    bar(conn, iid, D1, D(500), date(2026, 11, 1), volume=D(200))  # fetched after: already halved
    h = minute_history(conn, iid, D1, D1, adjust="split")
    assert (h.bars[0].close, h.bars[0].volume, h.bars[0].factor) == (D(500), D(200), 1)
    action(conn, iid, date(2027, 1, 5), "split", num=D(10), den=D(1))  # later than the basis: x0.1
    h = minute_history(conn, iid, D1, D1, adjust="split")
    assert (h.bars[0].close, h.bars[0].volume) == (D(50), D(2000))


def test_bars_fetched_before_a_split_get_it_applied(env):
    conn, iid = env
    action(conn, iid, date(2025, 6, 12), "bonus", num=D(2), den=D(1))
    bar(conn, iid, D1, D(1000), date(2025, 6, 10), volume=D(100))  # basis day before the ex-date
    h = minute_history(conn, iid, D1, D1, adjust="split")
    assert (h.bars[0].close, h.bars[0].volume) == (D(500), D(200))


def test_unpriced_actions_are_reported_and_strict_refuses(env):
    conn, iid = env
    action(conn, iid, date(2025, 6, 12), "demerger", status="review")
    bar(conn, iid, D1, D(100), date(2026, 11, 1))
    h = minute_history(conn, iid, D1, D1, adjust="split")
    assert [u.kind for u in h.unapplied] == ["demerger"] and not h.clean
    with pytest.raises(UnadjustableError):
        minute_history(conn, iid, D1, D1, adjust="split", strict=True)
    assert minute_history(conn, iid, D2, D2, adjust="split").bars == []


def test_a_kite_backed_reader_serves_kites_daily_candles_with_each_days_basis(env):
    from datetime import timedelta

    from algo.data.reader import BarReader

    conn, iid = env
    conn.execute(
        "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,adjusted_through,"
        "dataset_version,ingested_at) VALUES (%s,%s,10,15,8,9,15,'kite',%s,1,%s)",
        (iid, ts(D1), date(2026, 11, 1), INGESTED),
    )
    conn.execute(  # an NSE bar for the same day must not leak into the Kite series
        "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,dataset_version,ingested_at)"
        " VALUES (%s,%s,1,1,1,1,1,'nse',1,%s)",
        (iid, ts(D1), INGESTED),
    )
    action(conn, iid, date(2027, 1, 5), "split", num=D(10), den=D(1))  # after the basis day: x0.1
    action(
        conn, iid, date(2025, 6, 12), "bonus", num=D(2), den=D(1)
    )  # inside the basis: already in the vendor prices
    rd = BarReader(conn, source="kite", publish_lag=timedelta(0))
    (b,) = rd.history(iid, D1, D1, adjust="split").bars
    assert (b.open, b.high, b.low, b.close, b.volume) == (
        D(1),
        D("1.5"),
        D("0.8"),
        D("0.9"),
        D(150),
    )
    assert b.ts == ts(D1)
    raw = rd.history(iid, D1, D1).bars[0]
    assert (raw.open, raw.close, raw.volume) == (D(10), D(9), D(15))  # as the vendor served it
    assert rd.issuer_history(iid, D1, D1, adjust="split").bars[0].close == D(
        "0.9"
    )  # same through the issuer path
    assert BarReader(conn, source="kite").load(999999).rows == []


def test_for_env_follows_the_setting_and_a_kite_issuer_read_merges_the_chains_actions(
    env, monkeypatch
):
    from datetime import timedelta

    from algo.data.reader import BarReader

    conn, new = env
    repo = InstrumentRepo(conn)
    x = conn.execute("SELECT exchange_id FROM exchange").fetchone()[0]
    old = repo.add_instrument(x, "XYZOLD")
    conn.execute(
        "INSERT INTO corporate_action_relationship (relationship_type, source_instrument_id,"
        " target_instrument_id, target_symbol, effective_date, evidence, review_decision_id, recorded_at)"
        " VALUES ('SAME_ISSUER_ISIN_CHANGE', %s, %s, 'XYZ', %s, '[\"c\"]'::jsonb, 1, now())",
        (old, new, date(2025, 1, 1)),
    )
    action(conn, old, date(2027, 1, 5), "split", num=D(10), den=D(1))  # recorded on the OLD isin
    conn.execute(
        "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,adjusted_through,"
        "dataset_version,ingested_at) VALUES (%s,%s,100,100,100,100,1,'kite',%s,1,%s)",
        (new, ts(D1), date(2026, 11, 1), INGESTED),
    )
    assert BarReader.for_env(conn).source == "nse"  # tests default to bhavcopy
    monkeypatch.setenv("ALGO_PRICE_SOURCE", "kite")
    rd = BarReader.for_env(conn)
    assert rd.source == "kite" and rd.visible_after == timedelta(hours=6, minutes=15)
    assert rd.issuer_history(new, D1, D1, adjust="split").bars[0].close == D(
        10
    )  # chain's split applied
    assert rd.load(new).lenient().history(D1, D1, adjust="split").bars[0].close == D(
        100
    )  # own actions only
