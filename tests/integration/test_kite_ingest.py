from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest

from algo.data.kite_ingest import load_minutes, map_universe, upsert_kite_instruments
from algo.data.providers.kite import Candle, KiteInstrument, KiteTokenExpired
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 11, 15, 0, tzinfo=UTC)  # 20:30 IST on 2026-11-11


def candle(day: date, minute: int, price="100", high=None, low=None):
    ts = datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST) + timedelta(minutes=minute)
    p = D(price)
    return Candle(
        ts.astimezone(UTC),
        p,
        D(high) if high else p + 1,
        D(low) if low else p - 1,
        p,
        D(1000 + minute),
        None,
    )


class FakeKite:
    """The injected client: serves candles per (from, to) window from a day -> [candle] map and records the calls."""

    def __init__(self, days: dict[date, list[Candle]], raises_on_call: int | None = None):
        self.days, self.calls, self.raises_on_call = days, [], raises_on_call

    def historical(self, token, interval, start, end, *, raw_sink=None):
        if raw_sink:
            raw_sink(b'{"raw":"' + str(start.date()).encode() + b'"}')
        self.calls.append((token, interval, start.date(), end.date()))
        if self.raises_on_call is not None and len(self.calls) == self.raises_on_call:
            raise KiteTokenExpired("session expired")
        out = []
        for d, cs in sorted(self.days.items()):
            if start.date() <= d <= end.date():
                out += cs
        return out


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    iid = repo.add_instrument(x, "RELIANCE", isin="INE002A01018")
    repo.add_alias(iid, "nse", "RELIANCE", date(2000, 1, 1))
    return conn, iid


def rows(conn, iid):
    return conn.execute(
        "SELECT (ts AT TIME ZONE 'Asia/Kolkata')::date, count(*) FROM bar_1m WHERE instrument_id=%s GROUP BY 1 ORDER BY 1",
        (iid,),
    ).fetchall()


def test_minutes_are_stored_in_windows_of_at_most_60_days_with_the_adjustment_basis_recorded(env):
    conn, iid = env
    days = {
        date(2026, 1, 5) + timedelta(days=i): [
            candle(date(2026, 1, 5) + timedelta(days=i), m) for m in range(3)
        ]
        for i in (0, 70)
    }
    kite = FakeKite(days)
    r = load_minutes(conn, kite, 738561, iid, date(2026, 1, 1), date(2026, 3, 31), NOW)
    assert [(c[2], c[3]) for c in kite.calls] == [
        (date(2026, 1, 1), date(2026, 3, 1)),
        (date(2026, 3, 2), date(2026, 3, 31)),
    ]
    assert all(c[1] == "minute" for c in kite.calls) and (
        r.loaded,
        r.empty,
        r.skipped,
        r.failed,
        r.rows,
    ) == (2, 0, 0, 0, 6)
    assert rows(conn, iid) == [(date(2026, 1, 5), 3), (date(2026, 3, 16), 3)]
    assert conn.execute(
        "SELECT DISTINCT source, adjusted_through, dataset_version FROM bar_1m"
    ).fetchall() == [("kite", date(2026, 11, 11), 1)]
    first = conn.execute(
        "SELECT open, high, low, close, volume, ts FROM bar_1m ORDER BY ts LIMIT 1"
    ).fetchone()
    assert first == (
        D(100),
        D(101),
        D(99),
        D(100),
        D(1000),
        datetime(2026, 1, 5, 3, 45, tzinfo=UTC),
    )  # 09:15 IST, exact decimals


def test_completed_windows_are_skipped_on_a_rerun_but_the_window_touching_today_is_always_refetched(
    env,
):
    conn, iid = env
    days = {date(2026, 11, 10): [candle(date(2026, 11, 10), 0)]}
    kite = FakeKite(days)
    load_minutes(conn, kite, 1, iid, date(2026, 10, 1), date(2026, 11, 11), NOW)
    again = FakeKite(days)
    r = load_minutes(conn, again, 1, iid, date(2026, 10, 1), date(2026, 11, 11), NOW)
    assert (
        len(kite.calls) == 1 and len(again.calls) == 1
    )  # the window ends today: it is fetched again
    assert r.rows == 0 and rows(conn, iid) == [
        (date(2026, 11, 10), 1)
    ]  # and adds nothing the second time (no duplicates)
    load_minutes(conn, FakeKite({}), 1, iid, date(2026, 1, 1), date(2026, 2, 28), NOW)
    again_old = FakeKite({})
    r2 = load_minutes(conn, again_old, 1, iid, date(2026, 1, 1), date(2026, 2, 28), NOW)
    assert again_old.calls == [] and (r2.skipped, r2.loaded, r2.empty) == (
        1,
        0,
        0,
    )  # a finished (even empty) window is not asked twice


def test_a_window_with_no_candles_is_recorded_as_empty(env):
    conn, iid = env
    r = load_minutes(conn, FakeKite({}), 1, iid, date(2026, 1, 1), date(2026, 1, 31), NOW)
    assert (r.empty, r.loaded, r.rows) == (1, 0, 0)
    assert conn.execute("SELECT status, candles FROM kite_fetch").fetchall() == [("empty", 0)]


def test_a_window_with_inconsistent_prices_is_refused_whole_and_marked_failed(env):
    conn, iid = env
    bad = {
        date(2026, 1, 5): [
            candle(date(2026, 1, 5), 0),
            candle(date(2026, 1, 5), 1, price="100", high="90", low="95"),
        ]
    }  # high below low
    r = load_minutes(conn, FakeKite(bad), 1, iid, date(2026, 1, 1), date(2026, 1, 31), NOW)
    assert (r.failed, r.loaded, r.rows) == (1, 0, 0) and rows(conn, iid) == []
    status, detail = conn.execute("SELECT status, detail FROM kite_fetch").fetchone()
    assert status == "failed" and "high below" in detail


def test_an_expired_session_stops_the_run_and_keeps_everything_loaded_so_far(env):
    conn, iid = env
    days = {date(2026, 1, 5): [candle(date(2026, 1, 5), 0)]}
    kite = FakeKite(days, raises_on_call=2)
    with pytest.raises(KiteTokenExpired):
        load_minutes(conn, kite, 1, iid, date(2026, 1, 1), date(2026, 3, 31), NOW)
    assert rows(conn, iid) == [(date(2026, 1, 5), 1)]  # the first window is safe
    assert (
        conn.execute("SELECT count(*) FROM kite_fetch").fetchone()[0] == 1
    )  # the interrupted one is not recorded as done
    resumed = FakeKite(days)
    r = load_minutes(conn, resumed, 1, iid, date(2026, 1, 1), date(2026, 3, 31), NOW)
    assert (r.skipped, r.empty) == (1, 1) and len(
        resumed.calls
    ) == 1  # picks up at the window it was in


def test_overlapping_candles_across_runs_never_duplicate(env):
    conn, iid = env
    days = {date(2026, 1, 5): [candle(date(2026, 1, 5), 0), candle(date(2026, 1, 5), 1)]}
    load_minutes(conn, FakeKite(days), 1, iid, date(2026, 1, 1), date(2026, 1, 31), NOW)
    load_minutes(
        conn, FakeKite(days), 1, iid, date(2026, 1, 3), date(2026, 1, 31), NOW
    )  # a different window over the same days
    assert rows(conn, iid) == [(date(2026, 1, 5), 2)]


def instr(token, sym, name="X"):
    return KiteInstrument(token, token + 1, sym, name, "NSE", "NSE", "EQ")


def test_universe_symbols_map_by_isin_then_symbol_with_series_suffixes_and_dummies_skipped(env):
    conn, iid = env
    repo = InstrumentRepo(conn)
    x = conn.execute("SELECT exchange_id FROM exchange").fetchone()[0]
    reit = repo.add_instrument(x, "EMBASSY", isin="INE041025011")
    repo.add_alias(reit, "nse", "EMBASSY", date(2020, 1, 1))
    hfcl = repo.add_instrument(x, "HFCL", isin="INE548A01028")
    repo.add_alias(hfcl, "nse", "HFCL", date(2000, 1, 1))
    kite = [instr(1, "RELIANCE"), instr(2, "EMBASSY-RR"), instr(3, "HFCL-BE"), instr(4, "NOBODY")]
    universe = [("RELIANCE", "INE002A01018", "EQ"), ("EMBASSY", "INE041025011", "RR"), ("HFCL", "INE548A01028", "BE"),
                ("DUMMYHEG", "DUM545A01024", "EQ"), ("GONE", "INE000000000", "EQ"), ("ORPHAN", "INE111A01011", "EQ")]  # fmt: skip
    m = map_universe(conn, kite, universe)
    assert {(k.tradingsymbol, i) for k, i in m.mapped} == {
        ("RELIANCE", iid),
        ("EMBASSY-RR", reit),
        ("HFCL-BE", hfcl),
    }
    assert dict(m.unmatched) == {
        "DUMMYHEG": "placeholder, not a real security",
        "GONE": "no Kite instrument",
        "ORPHAN": "no Kite instrument",
    }


def test_a_kite_symbol_whose_security_is_not_in_our_master_is_reported_not_guessed(env):
    conn, _ = env
    m = map_universe(conn, [instr(9, "NEWCO")], [("NEWCO", "INE999Z01011", "EQ")])
    assert m.mapped == [] and dict(m.unmatched) == {"NEWCO": "not in our instrument master"}


def test_the_kite_instrument_table_is_refreshed_idempotently(env):
    conn, iid = env
    m = map_universe(conn, [instr(1, "RELIANCE")], [("RELIANCE", "INE002A01018", "EQ")])
    assert upsert_kite_instruments(conn, m.mapped, NOW) == 1
    assert upsert_kite_instruments(conn, m.mapped, NOW) == 1  # refreshed, not duplicated
    assert conn.execute(
        "SELECT instrument_token, tradingsymbol, instrument_id FROM kite_instrument"
    ).fetchall() == [(1, "RELIANCE", iid)]


def test_every_response_is_archived_in_the_lake_and_its_hash_is_in_the_ledger_even_when_refused(
    env, tmp_path
):
    import gzip
    import hashlib

    from algo.data.lake import LocalLake

    conn, iid = env
    lake = LocalLake(tmp_path)
    bad = {
        date(2026, 1, 5): [
            candle(date(2026, 1, 5), 0),
            candle(date(2026, 1, 5), 1, high="90", low="95"),
        ]
    }
    load_minutes(
        conn, FakeKite(bad), 738561, iid, date(2026, 1, 1), date(2026, 1, 31), NOW, lake=lake
    )
    (m,) = lake.versions("kite", "minute_738561", date(2026, 1, 1))
    raw = gzip.decompress(lake.get(m))
    assert raw == b'{"raw":"2026-01-01"}' and "from=2026-01-01" in m.url
    status, sha = conn.execute("SELECT status, raw_sha256 FROM kite_fetch").fetchone()
    assert status == "failed" and sha == m.checksum == hashlib.sha256(lake.get(m)).hexdigest()


def test_without_a_lake_nothing_is_archived_and_the_hash_stays_empty(env):
    conn, iid = env
    load_minutes(conn, FakeKite({}), 1, iid, date(2026, 1, 1), date(2026, 1, 31), NOW)
    assert conn.execute("SELECT raw_sha256 FROM kite_fetch").fetchone() == (None,)


class FakeDayKite:
    """Serves one day candle per listed date (ts 00:00 IST like Kite) within each requested window."""

    def __init__(self, days: dict[date, tuple], raises: bool = False):
        self.days, self.calls, self.raises = days, [], raises

    def historical(self, token, interval, start, end, *, raw_sink=None):
        self.calls.append((token, interval, start.date(), end.date()))
        if self.raises:
            raise KiteTokenExpired("session expired")
        if raw_sink:
            raw_sink(b'{"day":"raw"}')
        return [
            Candle(datetime(d.year, d.month, d.day, tzinfo=IST).astimezone(UTC), *map(D, v), None)
            for d, v in sorted(self.days.items())
            if start.date() <= d <= end.date()
        ]


GOOD = {
    date(2026, 1, 5): ("100", "105", "99", "104", "5000"),
    date(2026, 1, 6): ("104", "106", "103", "105", "6000"),
}


def day_rows(conn, iid):
    return conn.execute(
        "SELECT (ts AT TIME ZONE 'Asia/Kolkata')::time, (ts AT TIME ZONE 'Asia/Kolkata')::date, open, high, low, close,"
        " volume, source, adjusted_through, dataset_version, series FROM bar_1d WHERE instrument_id=%s AND source='kite'"
        " ORDER BY ts",
        (iid,),
    ).fetchall()


def test_kite_day_candles_are_stored_at_the_session_open_with_their_adjustment_basis(env):
    from datetime import time

    from algo.data.kite_ingest import load_days

    conn, iid = env
    kite = FakeDayKite(GOOD)
    r = load_days(conn, kite, 738561, iid, date(2026, 1, 1), date(2026, 1, 31), NOW)
    assert (r.loaded, r.rows) == (1, 2) and kite.calls == [
        (738561, "day", date(2026, 1, 1), date(2026, 1, 31))
    ]
    assert day_rows(conn, iid) == [
        (
            time(9, 15),
            date(2026, 1, 5),
            D(100),
            D(105),
            D(99),
            D(104),
            D(5000),
            "kite",
            date(2026, 11, 11),
            1,
            None,
        ),
        (
            time(9, 15),
            date(2026, 1, 6),
            D(104),
            D(106),
            D(103),
            D(105),
            D(6000),
            "kite",
            date(2026, 11, 11),
            1,
            None,
        ),
    ]
    assert conn.execute("SELECT status, candles FROM kite_day_fetch").fetchone() == ("loaded", 2)


def test_day_windows_are_at_most_2000_days_skipped_when_done_but_the_one_touching_today_is_refetched(
    env,
):
    from algo.data.kite_ingest import load_days

    conn, iid = env
    kite = FakeDayKite(GOOD)
    load_days(conn, kite, 1, iid, date(2020, 1, 1), date(2026, 1, 31), NOW)
    assert [(c[2], c[3]) for c in kite.calls] == [
        (date(2020, 1, 1), date(2025, 6, 22)),
        (date(2025, 6, 23), date(2026, 1, 31)),
    ]
    again = FakeDayKite(GOOD)
    r = load_days(conn, again, 1, iid, date(2020, 1, 1), date(2026, 1, 31), NOW)
    assert again.calls == [] and r.skipped == 2
    today = FakeDayKite({})
    load_days(conn, today, 1, iid, date(2026, 11, 1), date(2026, 11, 11), NOW)
    load_days(conn, today, 1, iid, date(2026, 11, 1), date(2026, 11, 11), NOW)
    assert len(today.calls) == 2  # the window ending today is asked again


def test_an_inconsistent_day_window_is_refused_whole_and_an_expired_session_propagates(
    env, tmp_path
):
    import gzip

    from algo.data.kite_ingest import load_days
    from algo.data.lake import LocalLake

    conn, iid = env
    bad = {date(2026, 1, 5): ("100", "90", "95", "100", "5")}  # high below low
    lake = LocalLake(tmp_path)
    r = load_days(
        conn, FakeDayKite(bad), 9, iid, date(2026, 1, 1), date(2026, 1, 31), NOW, lake=lake
    )
    assert (r.failed, r.rows) == (1, 0) and day_rows(conn, iid) == []
    status, sha = conn.execute("SELECT status, raw_sha256 FROM kite_day_fetch").fetchone()
    (m,) = lake.versions("kite", "day_9", date(2026, 1, 1))
    assert (
        status == "failed"
        and sha == m.checksum
        and gzip.decompress(lake.get(m)) == b'{"day":"raw"}'
    )
    with pytest.raises(KiteTokenExpired):
        load_days(
            conn, FakeDayKite({}, raises=True), 9, iid, date(2026, 2, 1), date(2026, 2, 28), NOW
        )


def test_kites_all_zero_placeholder_day_candles_before_a_listing_are_dropped_not_fatal(env):
    from algo.data.kite_ingest import load_days

    conn, iid = env
    zero = {
        date(2026, 1, 3): ("0", "0", "0", "0", "7154666")
    }  # no price at all, even though a volume is attached
    r = load_days(
        conn, FakeDayKite({**zero, **GOOD}), 5, iid, date(2026, 1, 1), date(2026, 1, 31), NOW
    )
    assert (r.loaded, r.failed, r.rows) == (1, 0, 2)  # only the two real candles are stored
    assert [d[1] for d in day_rows(conn, iid)] == [date(2026, 1, 5), date(2026, 1, 6)]
    detail, n = conn.execute("SELECT detail, candles FROM kite_day_fetch").fetchone()
    assert "1 candle(s) without any price dropped" in detail and n == 2
    # a candle with SOME prices but not all is real damage and still refuses the window
    bad = {date(2026, 2, 5): ("0", "5", "0", "3", "100")}
    assert (
        load_days(conn, FakeDayKite(bad), 6, iid, date(2026, 2, 1), date(2026, 2, 28), NOW).failed
        == 1
    )


def test_a_routine_day_load_leaves_frozen_days_alone_and_still_adds_the_days_after_the_freeze(env):
    from algo.data import freeze
    from algo.data.kite_ingest import load_days

    conn, iid = env
    d1, d2, d3 = date(2026, 11, 5), date(2026, 11, 6), date(2026, 11, 9)
    row = ("100", "105", "99", "104", "5000")
    load_days(
        conn, FakeDayKite({d1: row, d2: row}), 1, iid, date(2026, 11, 1), date(2026, 11, 11), NOW
    )
    frozen = freeze.take(conn, "kite", d2, NOW, "history frozen")
    # the daily job asks for the last week again, so the window holds the frozen days and one new day
    r = load_days(
        conn,
        FakeDayKite({d1: row, d2: row, d3: row}),
        1,
        iid,
        date(2026, 11, 1),
        date(2026, 11, 11),
        NOW,
    )
    assert (r.failed, r.rows) == (0, 1)  # only the day after the freeze is new
    assert [x[1] for x in day_rows(conn, iid)] == [d1, d2, d3]
    assert freeze.verify(conn, frozen) == []  # the frozen rows are exactly as they were


def test_a_superseded_token_is_not_asked_for_but_a_history_only_stock_still_is(env):
    from algo.data.kite_ingest import day_work

    conn, iid = env  # RELIANCE
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XBSE", "IN", "Asia/Kolkata", "INR", "BSE")
    other = repo.add_instrument(x, "HISTONLY", isin="INE000000001")
    for token, symbol, instrument, active in (
        (1, "RELIANCE-OLD", iid, False),  # the stock moved series: the old token is dead at Kite
        (2, "RELIANCE", iid, True),
        (
            3,
            "HISTONLY",
            other,
            False,
        ),  # mapped for history only, never followed by the feed: still valid
    ):
        conn.execute(
            "INSERT INTO kite_instrument (instrument_token, exchange_token, tradingsymbol, name, instrument_id,"
            " refreshed_at, active) VALUES (%s,%s,%s,'n',%s,%s,%s)",
            (token, token, symbol, instrument, NOW, active),
        )
    conn.execute(
        "INSERT INTO kite_instrument (instrument_token, exchange_token, tradingsymbol, name, instrument_id,"
        " refreshed_at, active) VALUES (4, 4, 'UNMAPPED', 'n', NULL, %s, true)",
        (NOW,),
    )
    assert day_work(conn) == [(3, "HISTONLY", other), (2, "RELIANCE", iid)]


def test_a_token_missing_from_the_latest_kite_list_is_not_asked_for(env):
    from datetime import timedelta

    from algo.data.kite_ingest import day_work

    conn, iid = env
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XBSE", "IN", "Asia/Kolkata", "INR", "BSE")
    dropped = repo.add_instrument(x, "DROPPED", isin="INE000000002")
    hist = repo.add_instrument(x, "HISTONLY", isin="INE000000001")
    for token, symbol, instrument, seen, active in (
        (1, "RELIANCE", iid, NOW, True),
        (
            2,
            "DROPPED",
            dropped,
            NOW - timedelta(days=1),
            False,
        ),  # not in Kite's newest list: "invalid token"
        (3, "HISTONLY", hist, NOW, False),  # still listed, just not followed by the feed
    ):
        conn.execute(
            "INSERT INTO kite_instrument (instrument_token, exchange_token, tradingsymbol, name, instrument_id,"
            " refreshed_at, active) VALUES (%s,%s,%s,'n',%s,%s,%s)",
            (token, token, symbol, instrument, seen, active),
        )
    assert [w[1] for w in day_work(conn)] == ["HISTONLY", "RELIANCE"]


def test_the_be_series_are_not_asked_for(env):
    from algo.data.kite_ingest import day_work

    conn, iid = env
    for token, symbol in ((1, "RELIANCE"), (2, "AARTISURF-BE"), (3, "SHIVAM-RE1-BE")):
        conn.execute(
            "INSERT INTO kite_instrument (instrument_token, exchange_token, tradingsymbol, name, instrument_id,"
            " refreshed_at, active) VALUES (%s,%s,%s,'n',%s,%s,true)",
            (token, token, symbol, iid, NOW),
        )
    assert day_work(conn) == [(1, "RELIANCE", iid)]


def test_a_revising_load_stores_a_changed_candle_as_a_new_version_and_leaves_identical_ones_alone(
    env,
):
    from algo.data import freeze
    from algo.data.kite_ingest import load_days

    conn, iid = env
    d1, d2, d3 = date(2026, 11, 5), date(2026, 11, 6), date(2026, 11, 9)
    evening = {d: ("100", "105", "99", "104", "5000") for d in (d1, d2, d3)}
    load_days(conn, FakeDayKite(evening), 1, iid, date(2026, 11, 1), date(2026, 11, 11), NOW)
    final = {
        **evening,
        d3: ("100", "107", "99", "106", "5200"),
    }  # the last day's close was provisional
    # the routine evening load never overwrites: the provisional candle stays
    r = load_days(conn, FakeDayKite(final), 1, iid, date(2026, 11, 1), date(2026, 11, 11), NOW)
    assert r.rows == 0 and [x[5] for x in day_rows(conn, iid)] == [D(104)] * 3
    # the morning load revises: one new version for the day that changed, nothing for the others
    r = load_days(
        conn, FakeDayKite(final), 1, iid, date(2026, 11, 1), date(2026, 11, 11), NOW, revise=True
    )
    assert r.rows == 1
    rows = day_rows(conn, iid)
    assert [(x[1], x[5], x[9]) for x in rows if x[1] == d3] == [(d3, D(104), 1), (d3, D(106), 2)]
    assert [x[9] for x in rows if x[1] != d3] == [1, 1]
    assert (
        load_days(
            conn,
            FakeDayKite(final),
            1,
            iid,
            date(2026, 11, 1),
            date(2026, 11, 11),
            NOW,
            revise=True,
        ).rows
        == 0
    )  # a second revise finds nothing new
    # frozen days are never revised, even when the vendor now says something else
    frozen = freeze.take(conn, "kite", d2, NOW, "history frozen")
    moved = {**final, d1: ("1", "1", "1", "1", "1"), d2: ("2", "2", "2", "2", "2")}
    load_days(
        conn, FakeDayKite(moved), 1, iid, date(2026, 11, 1), date(2026, 11, 11), NOW, revise=True
    )
    assert freeze.verify(conn, frozen) == []
    assert [x[9] for x in day_rows(conn, iid) if x[1] in (d1, d2)] == [1, 1]
