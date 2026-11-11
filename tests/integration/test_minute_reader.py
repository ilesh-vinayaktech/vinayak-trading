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
