from datetime import UTC, date, datetime
from decimal import Decimal as D

import pytest

from algo.data.corporate_actions import knowledge_time_for
from algo.data.reader import BarReader, UnadjustableError
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
INGESTED = datetime(2026, 11, 6, tzinfo=UTC)
# Mon 9 Jun .. Fri 13 Jun 2025; bonus 1:1 (price x0.5) with ex-date Thu 12 Jun
DAYS = [
    date(2025, 6, 9),
    date(2025, 6, 10),
    date(2025, 6, 11),
    date(2025, 6, 12),
    date(2025, 6, 13),
]
CLOSES = [D(1000), D(1010), D(1020), D(510), D(515)]


def ts(d):
    return datetime(d.year, d.month, d.day, 3, 45, tzinfo=UTC)  # 09:15 IST = bar-open


def utc(*a):
    return datetime(*a, tzinfo=UTC)


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    iid = repo.add_instrument(x, "XYZ")
    for d, c in zip(DAYS, CLOSES, strict=True):
        bar(conn, iid, d, c)
    return conn, iid, BarReader(conn)


def bar(conn, iid, d, close, *, version=1, source="nse", volume=D(100)):
    conn.execute(
        "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,dataset_version,"
        "ingested_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (iid, ts(d), close, close, close, close, volume, source, version, INGESTED),
    )


def action(conn, iid, ex, kind, status="ok", num=None, den=None, amount=None):
    conn.execute(
        "INSERT INTO corporate_action (instrument_id,ex_date,kind,status,num,den,amount,subject,"
        "knowledge_time,knowledge_time_source,source,raw_checksum,ingested_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,'t',%s,'ex_date_proxy','nse','x',%s)",
        (iid, ex, kind, status, num, den, amount, knowledge_time_for(ex), INGESTED),
    )


def closes(h):
    return [b.close for b in h.bars]


def test_raw_bars_and_latest_dataset_version_wins(env):
    conn, iid, rd = env
    bar(conn, iid, DAYS[1], D(1011), version=2)  # NSE-corrected re-ingest
    h = rd.history(iid, DAYS[0], DAYS[4])
    assert closes(h) == [D(1000), D(1011), D(1020), D(510), D(515)] and h.unapplied == []
    assert h.bars[0].ts == ts(DAYS[0]) and h.bars[0].factor == 1


def test_range_is_inclusive_and_other_sources_are_ignored(env):
    conn, iid, rd = env
    bar(conn, iid, DAYS[1], D(9999), source="other")
    assert closes(rd.history(iid, DAYS[1], DAYS[2])) == [D(1010), D(1020)]
    assert rd.history(iid, DAYS[3], DAYS[1]).bars == []  # start after end
    assert rd.history(999999, DAYS[0], DAYS[4]).bars == []  # unknown instrument


def test_split_adjusted_prices_and_volume_are_continuous_across_a_bonus(env):
    conn, iid, rd = env
    action(conn, iid, DAYS[3], "bonus", num=D(2), den=D(1))
    h = rd.history(iid, DAYS[0], DAYS[4], adjust="split")
    assert closes(h) == [D(500), D(505), D(510), D(510), D(515)]  # pre-ex halved, ex-day on as is
    assert [b.volume for b in h.bars] == [D(200), D(200), D(200), D(100), D(100)]  # shares doubled
    assert [b.factor for b in h.bars] == [D("0.5")] * 3 + [D(1)] * 2
    assert h.bars[2].close == h.bars[3].close  # continuity at the ex-date


def test_open_high_low_are_adjusted_too(env):
    conn, iid, rd = env
    conn.execute(
        "UPDATE bar_1d SET open=1000, high=1040, low=990, close=1020 WHERE ts=%s", (ts(DAYS[2]),)
    )
    action(conn, iid, DAYS[3], "bonus", num=D(2), den=D(1))
    b = rd.history(iid, DAYS[2], DAYS[2], adjust="split").bars[0]
    assert (b.open, b.high, b.low, b.close) == (D(500), D(520), D(495), D(510))


def test_point_in_time_an_action_is_invisible_before_its_knowledge_time(env):
    conn, iid, rd = env
    action(conn, iid, DAYS[3], "bonus", num=D(2), den=D(1))  # known from 2025-06-11 18:30Z
    before = rd.history(iid, DAYS[0], DAYS[4], adjust="split", as_of=utc(2025, 6, 11, 18, 29))
    assert closes(before) == [D(1000), D(1010), D(1020)]  # unadjusted: the split is not known yet
    at = rd.history(iid, DAYS[0], DAYS[4], adjust="split", as_of=utc(2025, 6, 12, 14, 0))
    assert closes(at) == [D(500), D(505), D(510), D(510)]  # now known, applied to the past


def test_bar_visible_only_after_close_plus_publish_lag(env):
    _, iid, rd = env
    d3 = DAYS[2]  # bar-open 03:45Z + 6h15 session + 3h publish lag = 13:00Z
    assert closes(rd.history(iid, d3, d3, as_of=utc(2025, 6, 11, 12, 59))) == []
    assert closes(rd.history(iid, d3, d3, as_of=utc(2025, 6, 11, 13, 0))) == [D(1020)]


def test_as_of_none_is_full_hindsight_and_naive_as_of_is_rejected(env):
    _, iid, rd = env
    assert len(rd.history(iid, DAYS[0], DAYS[4]).bars) == 5
    with pytest.raises(ValueError):
        rd.history(iid, DAYS[0], DAYS[4], as_of=datetime(2025, 6, 12))  # noqa: DTZ001
    with pytest.raises(ValueError, match="adjust"):
        rd.history(iid, DAYS[0], DAYS[4], adjust="magic")


def test_total_return_includes_dividends_but_split_series_does_not(env):
    conn, iid, rd = env
    action(conn, iid, DAYS[3], "bonus", num=D(2), den=D(1))
    action(conn, iid, DAYS[2], "dividend", amount=D(10))  # prev close (d2) = 1010
    split = rd.history(iid, DAYS[0], DAYS[1], adjust="split")
    tr = rd.history(iid, DAYS[0], DAYS[1], adjust="total_return")
    assert closes(split) == [D(500), D(505)]
    div_factor = 1 - D(10) / D(1010)
    assert tr.bars[0].close == pytest.approx(D(500) * div_factor, rel=D("1e-20"))
    assert tr.bars[0].volume == D(200)  # volume follows splits only, never dividends


def test_unpriceable_action_is_reported_and_strict_mode_refuses(env):
    conn, iid, rd = env
    action(conn, iid, DAYS[3], "demerger", status="review")
    h = rd.history(iid, DAYS[0], DAYS[4], adjust="split")
    assert [u.kind for u in h.unapplied] == [
        "demerger"
    ]  # prices before 12 Jun are NOT demerger-adjusted
    with pytest.raises(UnadjustableError, match="demerger"):
        rd.history(iid, DAYS[0], DAYS[4], adjust="split", strict=True)
    # it only matters if a returned bar lies before the ex-date
    assert rd.history(iid, DAYS[3], DAYS[4], adjust="split", strict=True).bars
    # raw prices were never adjusted, so strict has nothing to protect
    assert rd.history(iid, DAYS[0], DAYS[4], adjust="none", strict=True).bars


def test_percent_dividend_blocks_total_return_only(env):
    conn, iid, rd = env
    action(conn, iid, DAYS[2], "dividend", status="review")
    assert rd.history(iid, DAYS[0], DAYS[4], adjust="split", strict=True).bars
    with pytest.raises(UnadjustableError):
        rd.history(iid, DAYS[0], DAYS[4], adjust="total_return", strict=True)


def test_dividend_without_prior_bar_is_unapplied_not_an_error(env):
    conn, iid, rd = env
    action(conn, iid, date(2025, 6, 2), "dividend", amount=D(5))  # before the first bar
    h = rd.history(iid, DAYS[0], DAYS[4], adjust="total_return")
    assert closes(h) == CLOSES  # nothing earlier than the data to adjust


def test_unpriceable_action_hidden_by_as_of_is_not_reported(env):
    conn, iid, rd = env
    action(conn, iid, DAYS[3], "demerger", status="review")
    h = rd.history(iid, DAYS[0], DAYS[2], adjust="split", as_of=utc(2025, 6, 11, 14, 0))
    assert h.unapplied == []  # not knowable yet at that time


def test_real_world_shape_two_actions_one_day(env):
    conn, iid, rd = env
    action(conn, iid, DAYS[3], "bonus", num=D(5), den=D(1))  # Bajaj 2025: 4:1 bonus ...
    action(conn, iid, DAYS[3], "split", num=D(2), den=D(1))  # ... and a 2:1 split, same day
    h = rd.history(iid, DAYS[0], DAYS[0], adjust="split")
    assert h.bars[0].factor == D("0.1") and h.bars[0].close == D(100)
