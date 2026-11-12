import hashlib
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from algo.data.lake import LocalLake
from algo.data.providers.kite import KiteError, parse_instruments
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.live.bar_store import token_map
from algo.live.instrument_refresh import last_refresh, refresh

pytestmark = pytest.mark.integration
DAY1 = datetime(2026, 11, 12, 2, 0, tzinfo=UTC)  # 07:30 IST
DAY2 = datetime(2026, 11, 13, 2, 0, tzinfo=UTC)
HEADER = "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange\n"
ISIN = {"AAA": 0, "BBB": 1, "CCC": 2, "NEWCO": 3, "GHOST": 8, "DUMMYX": 9}


def dump(*rows):
    """A Kite instrument dump (all exchanges): rows are (token, symbol, instrument_type, segment, exchange)."""
    body = "".join(
        f"{t},{t // 256},{s},{s} LTD,0,,0,0.05,1,{it},{seg},{ex}\n" for t, s, it, seg, ex in rows
    )
    return (HEADER + body).encode()


def eq(token, symbol):
    return (token, symbol, "EQ", "NSE", "NSE")


class FakeKite:
    def __init__(self, raw: bytes | Exception):
        self.raw, self.calls = raw, []

    def instruments(self, exchange=None, *, raw_sink=None):
        self.calls.append(exchange)
        if isinstance(self.raw, Exception):
            raise self.raw
        if raw_sink:
            raw_sink(self.raw)
        return parse_instruments(self.raw)


def put_list(lake: Path, day: str, symbols):
    d = lake / "raw/niftyindices/nifty500_list" / f"dt={day}"
    d.mkdir(parents=True, exist_ok=True)
    rows = "".join(f"{s} Ltd.,X,{s},EQ,INE{ISIN[s]:09d}\n" for s in symbols)
    (d / "v1.bin").write_bytes(("Company Name,Industry,Symbol,Series,ISIN Code\n" + rows).encode())


@pytest.fixture
def env(conn, tmp_path):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    for sym in ("AAA", "BBB", "CCC", "NEWCO"):
        iid = repo.add_instrument(x, sym, isin=f"INE{ISIN[sym]:09d}")
        repo.add_alias(iid, "nse", sym, date(2000, 1, 1))
    put_list(tmp_path, "2026-11-07", ["AAA", "BBB", "CCC"])
    return conn, tmp_path


def run(conn, lake, kite, now):
    return refresh(conn, kite, LocalLake(lake), lake, now=now)


def test_the_whole_dump_is_archived_and_the_universe_is_mapped_to_tokens(env):
    conn, lake = env
    raw = dump(
        eq(101, "AAA"), eq(102, "BBB"), eq(103, "CCC"), eq(104, "NEWCO"),
        (900, "NIFTY26NOVFUT", "FUT", "NFO-FUT", "NFO"),
        (901, "AAA-BE", "EQ", "NSE", "NSE"),
    )  # fmt: skip
    kite = FakeKite(raw)
    r = run(conn, lake, kite, DAY1)
    assert kite.calls == [None]  # the full dump, every exchange, not just the NSE slice
    assert (r.total_rows, r.nse_equities, r.mapped) == (6, 5, 3)
    assert (r.unmatched, r.added, r.dropped) == ([], ["AAA", "BBB", "CCC"], [])
    assert r.raw_sha256 == hashlib.sha256(raw).hexdigest()
    archived = list((lake / "raw/kite/instruments").glob("dt=*/v*.bin"))
    assert (
        len(archived) == 1 and archived[0].read_bytes() == raw
    )  # byte for byte, derivatives included
    assert set(token_map(conn)) == {101, 102, 103}  # NEWCO is in the dump but not in the index list
    assert last_refresh(conn) == date(2026, 11, 12)


def test_the_next_day_reports_what_changed_and_the_feed_only_follows_live_instruments(env):
    conn, lake = env
    run(conn, lake, FakeKite(dump(eq(101, "AAA"), eq(102, "BBB"), eq(103, "CCC"))), DAY1)
    put_list(lake, "2026-11-12", ["AAA", "CCC", "NEWCO"])  # BBB left the index list, NEWCO joined
    nxt = dump(
        eq(111, "AAA"), eq(103, "CCC"), eq(104, "NEWCO"), eq(102, "BBB")
    )  # AAA got a new token
    r = run(conn, lake, FakeKite(nxt), DAY2)
    assert r.added == ["NEWCO"] and r.dropped == ["BBB"] and r.token_changes == [("AAA", 101, 111)]
    assert set(token_map(conn)) == {
        111,
        103,
        104,
    }  # AAA on its new token; BBB and the old AAA token are off
    assert conn.execute("SELECT count(*) FROM kite_instrument WHERE NOT active").fetchone() == (
        2,
    )  # kept for history
    assert last_refresh(conn) == date(2026, 11, 13)


def test_a_symbol_missing_from_the_dump_is_reported_with_the_other_unmappable_ones(env):
    conn, lake = env
    put_list(lake, "2026-11-08", ["AAA", "BBB", "CCC", "GHOST", "DUMMYX"])
    r = run(
        conn, lake, FakeKite(dump(eq(101, "AAA"), eq(102, "BBB"))), DAY1
    )  # CCC and GHOST missing from Kite
    assert r.mapped == 2
    assert {s for s, _ in r.unmatched} == {"CCC", "GHOST", "DUMMYX"}
    assert set(token_map(conn)) == {101, 102}


def test_running_twice_on_one_day_changes_nothing_and_a_failed_fetch_leaves_the_old_mapping(env):
    conn, lake = env
    raw = dump(eq(101, "AAA"), eq(102, "BBB"), eq(103, "CCC"))
    run(conn, lake, FakeKite(raw), DAY1)
    again = run(conn, lake, FakeKite(raw), DAY1)
    assert again.added == [] and again.dropped == []
    assert (
        len(list((lake / "raw/kite/instruments").glob("dt=*/v*.bin"))) == 1
    )  # identical payload: not stored twice
    assert conn.execute("SELECT count(*) FROM kite_instrument_refresh").fetchone() == (1,)
    with pytest.raises(KiteError):
        run(conn, lake, FakeKite(KiteError("Kite is down")), DAY2)
    assert set(token_map(conn)) == {101, 102, 103} and last_refresh(conn) == date(2026, 11, 12)


def test_before_the_first_refresh_there_is_no_last_date(env):
    conn, _ = env
    assert last_refresh(conn) is None


def test_a_missing_index_list_is_reported_not_guessed_at(conn, tmp_path):
    migrate(conn)
    from algo.live.instrument_refresh import RefreshError

    with pytest.raises(RefreshError, match="no nifty500_list"):
        run(conn, tmp_path, FakeKite(dump(eq(101, "AAA"))), DAY1)


def test_the_whole_market_is_followed_when_asked_not_just_the_index_list(env):
    conn, lake = env
    raw = dump(eq(101, "AAA"), eq(102, "BBB"), eq(103, "CCC"), eq(104, "NEWCO"))
    r = refresh(conn, FakeKite(raw), LocalLake(lake), lake, now=DAY1, whole_market=True)
    assert r.mapped == 4 and set(token_map(conn)) == {
        101,
        102,
        103,
        104,
    }  # NEWCO is in our master, not the index list
