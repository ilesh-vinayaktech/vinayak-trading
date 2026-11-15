from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.screener import snapshot

pytestmark = pytest.mark.integration
LAST = date(2026, 11, 10)


def bars(conn, iid, closes, last=LAST):
    for i, c in enumerate(closes):
        day = last - timedelta(days=len(closes) - 1 - i)
        conn.execute(
            "INSERT INTO bar_1d (instrument_id, ts, open, high, low, close, volume, source, dataset_version, ingested_at)"
            " VALUES (%s,%s,%s,%s,%s,%s,1000000,'nse',1,now())",
            (iid, datetime.combine(day, datetime.min.time(), UTC), c, c, c, c),
        )


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    up = repo.add_instrument(x, "UPPER", isin="INE000000001")
    split = repo.add_instrument(x, "SPLITTER", isin="INE000000002")
    stale = repo.add_instrument(x, "STALE", isin="INE000000003")
    bars(conn, up, range(100, 400))
    bars(conn, split, [1000] * 150 + [100] * 150)
    conn.execute(
        "INSERT INTO corporate_action (instrument_id, ex_date, kind, status, num, den, subject, knowledge_time, knowledge_time_source, source, raw_checksum, ingested_at) VALUES (%s,%s,'split','ok',10,1,'t',now(),'test','t','x',now())",
        (split, LAST - timedelta(days=149)),
    )
    for i, end in enumerate(
        (date(2025, 12, 31), date(2026, 3, 31), date(2026, 6, 30), date(2026, 9, 30))
    ):
        fid = conn.execute(
            "INSERT INTO fundamental_filing (symbol, isin, instrument_id, seq_number, period_start, period_end, basis, audited, bank,"
            " filed_at, rounding, xbrl_url, raw_sha256, ingested_at) VALUES ('UPPER','INE000000001',%s,%s,%s,%s,'CONSOLIDATED',false,false,%s,'Crores','u','x',now())"
            " RETURNING filing_id",
            (
                up,
                str(i),
                end - timedelta(days=89),
                end,
                datetime.combine(end + timedelta(days=40), datetime.min.time(), UTC),
            ),
        ).fetchone()[0]
        for metric, v in (("RevenueFromOperations", 1000), ("PaidUpValueOfEquityShareCapital", 100), ("FaceValueOfEquityShareCapital", 10), ("ProfitLossForPeriod", 100),
                          ("BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations", 5)):  # fmt: skip
            conn.execute(
                "INSERT INTO fundamental_fact VALUES (%s,%s,'QUARTER',%s)", (fid, metric, v)
            )
    conn.execute("INSERT INTO market_cap_list VALUES ('2026-06-30','2026-08-01',1,1,'u','x',now())")
    conn.execute(
        "INSERT INTO market_cap_rank VALUES ('2026-06-30',1,1,'INE000000001','UPPER','Upper',9999,'large',%s)",
        (up,),
    )
    bars(conn, stale, [50] * 30, last=LAST - timedelta(days=60))
    return conn, up, split


def test_snapshot_has_live_stocks_only_and_cuts_history_at_a_split(env):
    conn, up, split = env
    rows = {r["symbol"]: r for r in snapshot.build(conn)}
    assert set(rows) == {"UPPER", "SPLITTER"}  # STALE has no recent bar
    assert rows["UPPER"]["price_vs_sma200"] > 0 and rows["UPPER"]["chg_1y"] is not None
    assert rows["UPPER"]["segment"] == "large" and rows["UPPER"]["latest_period"] == "2026-09-30"
    assert D("19.9") < rows["UPPER"]["pe"] < D("20.0")  # price 399 / (4 quarters x 5)
    assert rows["SPLITTER"]["segment"] is None and "pe" not in rows["SPLITTER"]
    assert rows["SPLITTER"]["chg_1m"] == 0  # not -90%: the pre-split prices are ignored
    assert rows["SPLITTER"]["pct_from_52w_high"] == 0


def test_refresh_stores_the_table_and_build_reads_it_back_without_recalculating(env, monkeypatch):
    conn, _, _ = env
    assert snapshot.refresh(conn) == 2
    fresh = {r["symbol"]: r for r in snapshot.compute(conn)}
    monkeypatch.setattr(snapshot, "compute", lambda c: pytest.fail("recalculated on read"))
    stored = {r["symbol"]: r for r in snapshot.build(conn)}
    assert stored == fresh  # Decimals, text and missing figures survive the round trip
    assert isinstance(stored["UPPER"]["pe"], D) and stored["UPPER"]["segment"] == "large"


def test_build_builds_the_table_once_when_the_job_has_never_run(env):
    conn, _, _ = env
    assert conn.execute("SELECT count(*) FROM screener_snapshot").fetchone()[0] == 0
    assert len(snapshot.build(conn)) == 2
    assert conn.execute("SELECT count(*) FROM screener_snapshot").fetchone()[0] == 2


def test_the_sector_comes_from_the_dated_sector_table_as_of_the_snapshot_day(env):
    conn, up, split = env
    conn.execute(
        "INSERT INTO instrument_sector VALUES (%s,'IT',%s,'h',now())",
        (up, LAST - timedelta(days=30)),
    )
    conn.execute(
        "INSERT INTO instrument_sector VALUES (%s,'Autos',%s,'h',now())",
        (split, LAST + timedelta(days=5)),
    )  # starts after the snapshot day
    rows = {r["symbol"]: r for r in snapshot.compute(conn)}
    assert (
        rows["UPPER"]["sector"] == "IT" and rows["UPPER"]["pe_vs_sector"] is None
    )  # no peers with a P/E: no median
    assert rows["SPLITTER"]["sector"] is None
