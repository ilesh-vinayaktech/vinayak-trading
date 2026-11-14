"""Kite up to a cutoff day, NSE bhavcopy after it (ALGO_PRICE_SOURCE=bhavcopy + ALGO_PRICE_CUTOFF)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from algo.data.corporate_actions import knowledge_time_for
from algo.data.reader import BarReader, seam_mismatches
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
INGESTED = datetime(2026, 11, 6, tzinfo=UTC)
DAYS = [date(2025, 6, 9) + timedelta(days=i) for i in range(5)]  # Mon..Fri
CUT = DAYS[2]
BASIS = date(2026, 11, 1)  # the day Kite's history was adjusted through


def ts(d):
    return datetime(d.year, d.month, d.day, 3, 45, tzinfo=UTC)


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    return conn, repo.add_instrument(x, "XYZ"), repo.add_instrument(x, "ABC")


def bar(conn, iid, d, close, source, through=None, volume=100):
    conn.execute(
        "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,adjusted_through,"
        "dataset_version,ingested_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s)",
        (iid, ts(d), close, close, close, close, volume, source, through, INGESTED),
    )


def bonus(conn, iid, ex):  # 2:1, price x0.5
    conn.execute(
        "INSERT INTO corporate_action (instrument_id,ex_date,kind,status,num,den,subject,"
        "knowledge_time,knowledge_time_source,source,raw_checksum,ingested_at) VALUES"
        " (%s,%s,'bonus','ok',2,1,'t',%s,'ex_date_proxy','nse','x',%s)",
        (iid, ex, knowledge_time_for(ex), INGESTED),
    )


def both_feeds(conn, iid):
    for i, d in enumerate(DAYS):
        bar(conn, iid, d, 100 + i, "kite", BASIS)  # Kite has every day
        bar(conn, iid, d, 900 + i, "nse")  # NSE too, with different numbers so the source shows


def test_bars_up_to_the_cutoff_come_from_kite_and_later_ones_from_nse(env):
    conn, iid, _ = env
    both_feeds(conn, iid)
    rd = BarReader(conn, cutoff=CUT)
    closes = [(b.ts.date(), b.close) for b in rd.history(iid, DAYS[0], DAYS[-1]).bars]
    assert closes == [
        (DAYS[0], 100),
        (DAYS[1], 101),
        (DAYS[2], 102),
        (DAYS[3], 903),
        (DAYS[4], 904),
    ]
    assert [b.close for b in BarReader(conn).history(iid, DAYS[0], DAYS[-1]).bars] == [
        900,
        901,
        902,
        903,
        904,
    ]  # fmt: skip  (no cutoff: NSE only, as before)


def test_a_split_before_the_basis_day_is_not_applied_to_kite_bars_but_is_to_raw_nse_bars(env):
    conn, iid, _ = env
    both_feeds(conn, iid)
    bonus(conn, iid, date(2025, 6, 20))  # after the last bar, before Kite's basis day
    bars = BarReader(conn, cutoff=CUT).history(iid, DAYS[0], DAYS[-1], adjust="split").bars
    # Kite bars already contain it (x1); the raw NSE bars after the cutoff get x0.5
    assert [b.close for b in bars] == [100, 101, 102, D("451.5"), 452]
    assert [b.factor for b in bars] == [1, 1, 1, D("0.5"), D("0.5")]


def test_an_action_after_kites_basis_day_is_applied_to_both_halves(env):
    conn, iid, _ = env
    both_feeds(conn, iid)
    bonus(conn, iid, date(2026, 12, 1))  # Kite will never adjust for this one
    bars = BarReader(conn, cutoff=CUT).history(iid, DAYS[0], DAYS[-1], adjust="split").bars
    assert [b.close for b in bars] == [50, D("50.5"), 51, D("451.5"), 452]


def test_the_issuer_path_and_the_snapshot_hash_follow_the_same_rule(env):
    conn, iid, _ = env
    both_feeds(conn, iid)
    rd = BarReader(conn, cutoff=CUT, known_at=INGESTED + timedelta(days=1))
    assert [b.close for b in rd.issuer_history(iid, DAYS[0], DAYS[-1]).bars] == [
        100, 101, 102, 903, 904,
    ]  # fmt: skip
    pure = BarReader(conn, known_at=INGESTED + timedelta(days=1))
    h = rd.snapshot_hash([iid])
    assert h and h != pure.snapshot_hash([iid])
    assert BarReader(conn).snapshot_hash([iid]) is None  # unpinned, as before


def test_for_env_builds_the_stitched_reader_only_for_bhavcopy_with_a_cutoff(conn, monkeypatch):
    migrate(conn)
    monkeypatch.setenv("ALGO_PRICE_SOURCE", "bhavcopy")
    monkeypatch.setenv("ALGO_PRICE_CUTOFF", "2026-12-31")
    assert BarReader.for_env(conn).cutoff == date(2026, 12, 31)
    monkeypatch.delenv("ALGO_PRICE_CUTOFF")
    assert BarReader.for_env(conn).cutoff is None
    monkeypatch.setenv("ALGO_PRICE_SOURCE", "kite")
    monkeypatch.setenv("ALGO_PRICE_CUTOFF", "2026-12-31")
    with pytest.raises(ValueError, match="bhavcopy"):
        BarReader.for_env(conn)


def test_the_seam_check_lists_stocks_whose_two_closes_differ_on_the_cutoff_day(env):
    conn, a, b = env
    bar(conn, a, CUT, 100, "kite", BASIS)
    bar(conn, a, CUT, 100, "nse")  # agree
    bar(conn, b, CUT, 50, "kite", BASIS)
    bar(conn, b, CUT, 100, "nse")  # Kite already halved it: an action sits between
    bar(conn, a, DAYS[3], 1, "kite", BASIS)  # another day, ignored
    assert seam_mismatches(conn, CUT) == [(b, D(50), D(100))]
    assert seam_mismatches(conn, DAYS[4]) == []


def dividend(conn, iid, ex, amount):
    conn.execute(
        "INSERT INTO corporate_action (instrument_id,ex_date,kind,status,amount,subject,"
        "knowledge_time,knowledge_time_source,source,raw_checksum,ingested_at) VALUES"
        " (%s,%s,'dividend','ok',%s,'t',%s,'ex_date_proxy','nse','x',%s)",
        (iid, ex, amount, knowledge_time_for(ex), INGESTED),
    )


def feeds(conn, iid, kite_before_ex):
    """NSE raw 100 every day; Kite 100, or `kite_before_ex` on the days before the ex-date DAYS[3]."""
    for i, d in enumerate(DAYS):
        bar(conn, iid, d, 100, "nse")
        bar(conn, iid, d, kite_before_ex if i < 3 else 100, "kite", BASIS)


def test_a_dividend_kite_already_took_out_is_not_taken_out_again_in_total_return(env):
    conn, iid, _ = env
    feeds(conn, iid, kite_before_ex=90)  # Kite's history already net of the 10
    dividend(conn, iid, DAYS[3], 10)
    for rd in (
        BarReader(conn, source="kite", publish_lag=timedelta(0)),
        BarReader(conn, cutoff=CUT),
    ):
        closes = [b.close for b in rd.history(iid, DAYS[0], DAYS[2], adjust="total_return").bars]
        assert closes == [90, 90, 90]
        assert [
            b.close for b in rd.issuer_history(iid, DAYS[0], DAYS[2], adjust="total_return").bars
        ] == [90, 90, 90]


def test_a_dividend_kite_left_in_is_still_taken_out_in_total_return(env):
    conn, iid, _ = env
    feeds(conn, iid, kite_before_ex=100)
    dividend(conn, iid, DAYS[3], 10)
    rd = BarReader(conn, source="kite", publish_lag=timedelta(0))
    assert [b.close for b in rd.history(iid, DAYS[0], DAYS[2], adjust="total_return").bars] == [
        90,
        90,
        90,
    ]
    assert [b.close for b in rd.history(iid, DAYS[0], DAYS[2], adjust="split").bars] == [
        100,
        100,
        100,
    ]


def test_the_explorer_and_chart_readers_follow_the_cutoff_because_they_use_for_env(
    env, monkeypatch
):
    from algo.api import queries

    conn, iid, _ = env
    both_feeds(conn, iid)
    monkeypatch.setenv("ALGO_PRICE_SOURCE", "bhavcopy")
    monkeypatch.setenv("ALGO_PRICE_CUTOFF", str(CUT))
    reader, source = queries.reader_for(conn, iid)
    assert source == "nse" and reader.cutoff == CUT
    bars = queries.instrument_bars(conn, iid, DAYS[0], DAYS[-1], "none")["bars"]
    assert [b["close"] for b in bars] == ["100", "101", "102", "903", "904"]
