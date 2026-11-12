"""Which stocks a study may trade on each day: AMFI's segment lists as they stood then, limited to stocks we hold Kite history for."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from algo.data.amfi_caps import CapList, CapRow
from algo.data.market_caps import load_list
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.research.study import UniverseSpec
from algo.research.study_universe import build

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)
D0 = date(2024, 1, 1)


def sessions(n, start=D0):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def put(conn, iid, days, close=10, vol=1000, source="kite"):
    for d in days:
        conn.execute(
            "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,adjusted_through,dataset_version,ingested_at)"
            " VALUES (%s,%s,1,1,1,%s,%s,%s,%s,1,%s)",
            (
                iid,
                datetime(d.year, d.month, d.day, 3, 45, tzinfo=UTC),
                close,
                vol,
                source,
                date(2026, 11, 1) if source == "kite" else None,
                NOW,
            ),
        )


def row(rank, isin, nse):
    return CapRow(rank, isin, nse, f"Co {rank}", D(1000 - rank))


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    ids = {
        s: repo.add_instrument(x, s, isin=f"INE00000000{i}")
        for i, s in enumerate(("BIG", "MIDDLE", "SMALLY", "NODATA", "LATE"), 1)
    }
    for s in ("BIG", "MIDDLE", "SMALLY"):
        put(conn, ids[s], sessions(120))  # about 24 weeks of history from 2024-01-01
    put(conn, ids["LATE"], sessions(100, date(2024, 5, 1)))  # listed in May
    # the Jun 2023 list is relied on from 1 Aug 2023; the Dec 2023 one from 1 Feb 2024
    load_list(conn, CapList(date(2023, 6, 30), (row(1, "INE000000001", "BIG"), row(120, "INE000000002", "MIDDLE"), row(300, "INE000000003", "SMALLY"),
                                                 row(400, "INE000000004", "NODATA"))), "u1", "s1", NOW)  # fmt: skip
    load_list(conn, CapList(date(2023, 12, 31), (row(1, "INE000000001", "BIG"), row(260, "INE000000002", "MIDDLE"), row(300, "INE000000003", "SMALLY"),
                                                  row(450, "INE000000004", "NODATA"), row(90, "INE000000005", "LATE"))), "u2", "s2", NOW)  # fmt: skip
    return conn, ids


def test_a_stock_is_a_member_while_the_list_in_force_puts_it_in_a_chosen_segment(env):
    conn, ids = env
    m, cov = build(
        conn,
        UniverseSpec(segments=["large", "mid"], min_history_sessions=0),
        date(2024, 2, 1),
        date(2024, 7, 31),
    )
    assert m.on(date(2024, 1, 31)) == frozenset()  # before the study
    assert m.on(date(2024, 3, 1)) == {
        ids["BIG"]
    }  # on the Dec 2023 list MIDDLE (rank 260) is small and LATE has no bars yet
    assert m.on(date(2024, 8, 1)) == frozenset()  # past the study's end


def test_a_stock_that_changes_segment_leaves_when_the_new_list_takes_effect(env):
    conn, ids = env
    m, _ = build(
        conn,
        UniverseSpec(segments=["large", "mid"], min_history_sessions=0),
        date(2024, 1, 2),
        date(2024, 7, 31),
    )
    assert ids["MIDDLE"] in m.on(date(2024, 1, 31))  # the Jun 2023 list: rank 120 = mid
    assert ids["MIDDLE"] not in m.on(
        date(2024, 2, 1)
    )  # the Dec 2023 list (from 1 Feb): rank 260 = small
    m2, _ = build(
        conn,
        UniverseSpec(segments=["small"], min_history_sessions=0),
        date(2024, 1, 2),
        date(2024, 7, 31),
    )
    assert ids["MIDDLE"] in m2.on(date(2024, 2, 1)) and ids["SMALLY"] in m2.on(date(2024, 1, 31))


def test_only_stocks_we_hold_kite_history_for_are_usable_and_the_coverage_says_how_many_were_lost(
    env,
):
    conn, ids = env
    m, cov = build(
        conn,
        UniverseSpec(segments=["small", "micro"], min_history_sessions=0),
        date(2024, 1, 2),
        date(2024, 7, 31),
    )
    assert ids["NODATA"] not in m.ever()
    first, second = cov
    assert (
        first["list"],
        first["from"],
        first["in_segments"],
        first["matched"],
        first["usable"],
    ) == ("2023-06-30", "2024-01-02", 2, 2, 1)
    assert (
        second["list"],
        second["from"],
        second["in_segments"],
        second["matched"],
        second["usable"],
    ) == ("2023-12-31", "2024-02-01", 3, 3, 2)


def test_a_stock_joins_only_once_it_has_enough_history_and_a_later_listing_joins_later(env):
    conn, ids = env
    m, _ = build(
        conn,
        UniverseSpec(segments=["large", "mid", "small"], min_history_sessions=60),
        date(2024, 2, 1),
        date(2024, 7, 31),
    )
    ready = sessions(60)[-1]  # the 60th session since 2024-01-01
    assert ids["BIG"] not in m.on(ready - timedelta(days=1)) and ids["BIG"] in m.on(
        ready + timedelta(days=1)
    )
    late_ready = sessions(60, date(2024, 5, 1))[-1]
    assert ids["LATE"] not in m.on(late_ready - timedelta(days=1)) and ids["LATE"] in m.on(
        late_ready + timedelta(days=1)
    )
    assert ids["LATE"] not in m.on(date(2024, 2, 15))  # not yet traded then


def test_before_the_first_list_the_days_can_be_left_out_or_sized_by_traded_value(env):
    conn, ids = env
    skip = UniverseSpec(segments=["large"], min_history_sessions=0, before_segment_lists="skip")
    m, cov = build(conn, skip, date(2023, 3, 1), date(2024, 2, 29))
    assert m.on(date(2023, 6, 1)) == frozenset() and m.on(date(2024, 1, 31)) != frozenset()
    assert (
        cov[0]["from"] == "2023-08-01"
    )  # the study began earlier, but nothing before the first list counts
    put(
        conn, ids["BIG"], sessions(260, date(2022, 8, 1)), close=500, vol=10_000
    )  # trading before the first list: BIG heavily
    put(conn, ids["MIDDLE"], sessions(260, date(2022, 8, 1)), close=5, vol=10)
    stand_in, cov2 = build(
        conn,
        UniverseSpec(segments=["large"], min_history_sessions=0),
        date(2023, 6, 1),
        date(2023, 7, 31),
    )
    assert stand_in.on(date(2023, 6, 15)) == {
        ids["BIG"],
        ids["MIDDLE"],
    }  # SMALLY has no trading yet: it cannot be ranked
    assert cov2[0]["list"] == "traded value (stand-in)" and cov2[0]["usable"] == 2
    mid_only, _ = build(
        conn,
        UniverseSpec(segments=["mid"], min_history_sessions=0),
        date(2023, 6, 1),
        date(2023, 7, 31),
    )
    assert (
        mid_only.on(date(2023, 6, 15)) == frozenset()
    )  # with two ranked stocks, both are ranks 1-2: large


def test_with_no_lists_loaded_and_no_stand_in_there_is_nothing_to_trade(conn):
    migrate(conn)
    m, cov = build(
        conn,
        UniverseSpec(segments=["large"], before_segment_lists="skip"),
        date(2024, 1, 1),
        date(2024, 6, 30),
    )
    assert m.ever() == [] and cov == []


def test_a_period_that_ends_before_it_starts_has_no_members(env):
    conn, _ = env
    m, cov = build(conn, UniverseSpec(segments=["large"]), date(2024, 3, 1), date(2024, 2, 1))
    assert m.ever() == [] and cov == []
