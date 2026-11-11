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

    def historical(self, token, interval, start, end):
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
