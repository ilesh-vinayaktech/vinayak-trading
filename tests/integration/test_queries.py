from datetime import UTC, date, datetime
from decimal import Decimal as D

import pytest

from algo.api import queries
from algo.data.benchmark import ingest, register, store_validation
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 7, tzinfo=UTC)


def ts(d):
    return datetime(d.year, d.month, d.day, 3, 45, tzinfo=UTC)


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    iid = repo.add_instrument(x, "XYZ")
    for i, d in enumerate([date(2025, 6, 9), date(2025, 6, 10), date(2025, 6, 11)]):
        conn.execute(
            "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,dataset_version,"
            "ingested_at) VALUES (%s,%s,1,2,1,%s,100,'nse',1,%s)", (iid, ts(d), 1 + i, NOW))  # fmt: skip
    conn.execute(
        "INSERT INTO corporate_action (instrument_id,ex_date,kind,status,subject,knowledge_time,"
        "knowledge_time_source,source,raw_checksum,ingested_at) VALUES (%s,'2025-06-10','bonus','ok',"
        "'t',%s,'ex_date_proxy','nse','x',%s)", (iid, NOW, NOW))  # fmt: skip
    return conn, iid


def test_data_health_counts_bars_dates_and_partition_states(env):
    conn, iid = env
    for part, status in (("2025-06-09", "loaded"), ("2025-06-10", "quarantined"),
                         ("2025-06-11", "loaded")):  # fmt: skip
        conn.execute("INSERT INTO partition_load (source,dataset,partition,status,at) VALUES"
                     " ('nse','bhav',%s,%s,%s)", (part, status, NOW))  # fmt: skip
    conn.execute(
        "INSERT INTO partition_load (source,dataset,partition,status,at) VALUES"
        " ('nse','bhav','2025-06-10','loaded',%s)",
        (NOW,),
    )  # the quarantine was superseded
    conn.execute(
        "INSERT INTO partition_load (source,dataset,partition,status,at) VALUES"
        " ('nse','bhav','2025-06-12','noop',%s)",
        (NOW,),
    )  # a re-run of a loaded day
    h = queries.data_health(conn)
    assert (h["bars"], h["instruments_with_bars"], h["first_date"], h["last_date"]) == (
        3, 1, "2025-06-09", "2025-06-11")  # fmt: skip
    assert (h["bars_on_last_date"], h["bars_on_previous_date"]) == (1, 1)
    assert h["partitions"] == {"loaded": 4} and h["quarantined_partitions"] == []
    assert sum(h["instruments"].values()) == 1


def test_a_quarantined_partition_is_listed_and_no_bars_gives_an_empty_summary(conn):
    migrate(conn)
    empty = queries.data_health(conn)
    assert (
        empty["bars"] == 0
        and empty["bars_on_last_date"] == 0
        and empty["bars_on_previous_date"] is None
    )
    conn.execute("INSERT INTO partition_load (source,dataset,partition,status,at) VALUES"
                 " ('nse','bhav','2022-08-08','quarantined',%s)", (NOW,))  # fmt: skip
    assert queries.data_health(conn)["quarantined_partitions"] == ["2022-08-08"]


def test_instrument_search_detail_and_actions(env):
    conn, iid = env
    assert [r["symbol"] for r in queries.search_instruments(conn, "xy")] == ["XYZ"]
    assert queries.search_instruments(conn, "nothing") == []
    d = queries.instrument(conn, iid)
    assert d["symbol"] == "XYZ" and d["bars"] == {
        "first": "2025-06-09",
        "last": "2025-06-11",
        "count": 3,
    }
    assert queries.instrument(conn, 999999) is None
    assert queries.instrument_actions(conn, iid) == [{
        "ex_date": "2025-06-10", "kind": "bonus", "status": "ok", "num": None, "den": None,
        "amount": None, "subject": "t"}]  # fmt: skip


def test_bars_come_back_as_strings_with_the_adjustment_version(env):
    conn, iid = env
    raw = queries.instrument_bars(conn, iid, date(2025, 6, 9), date(2025, 6, 11), "none")
    assert (
        raw["adjust"] == "none"
        and raw["clean"]
        and [b["close"] for b in raw["bars"]] == ["1", "2", "3"]
    )
    assert raw["bars"][0]["date"] == "2025-06-09" and raw["bars"][0]["factor"] == "1"
    assert raw["unapplied"] == [] and raw["provisional"] == [] and raw["adjustment_version"]
    split = queries.instrument_bars(conn, iid, date(2025, 6, 9), date(2025, 6, 11), "split")
    assert split["adjust"] == "split" and split["adjustment_version"] != raw["adjustment_version"]


def seed_benchmark(conn, ids=(1,)):
    bid = register(conn, name="N200 TRI", provider="p", index_symbol="NIFTY 200",
                   return_type="TOTAL_RETURN", methodology_version="m")  # fmt: skip
    ingest(conn, bid, [(date(2024, 1, d), D(100 + d)) for d in range(1, 6)], source="s",
           source_timestamp=NOW, raw_hash="h", now=NOW)  # fmt: skip
    return bid


def test_benchmarks_levels_and_validation_history(conn):
    migrate(conn)
    bid = seed_benchmark(conn)
    b = queries.benchmarks(conn)[0]
    assert (b["id"], b["observations"], b["first"], b["last"]) == (
        bid,
        5,
        "2024-01-01",
        "2024-01-05",
    )
    assert len(b["dataset_hash"]) == 64
    store_validation(conn, bid, report={"report_version": "2", "technical_validation_passed": True,
                                        "check_states": {"a": "PASS"}}, passed=True,
                     normalized_sha256="n", factsheet_sha256="f", unresolved=["x"], now=NOW)  # fmt: skip
    store_validation(conn, bid, report={}, passed=False, normalized_sha256="n", factsheet_sha256=None,
                     unresolved=[], now=NOW)  # fmt: skip
    v = queries.benchmark_validations(conn, bid)
    assert [x["validation_id"] for x in v] == [2, 1]  # newest first
    assert v[0]["report_version"] == "legacy" and v[0]["technical_validation_passed"] is False
    assert v[1]["report_version"] == "2" and v[1]["covers_current_dataset"] is True
    assert v[1]["check_states"] == {"a": "PASS"} and v[1]["unresolved"] == ["x"]
    full = queries.benchmark_levels(conn, bid, None, None, 100)
    assert [p["date"] for p in full] == [f"2024-01-0{d}" for d in range(1, 6)] and full[0][
        "level"
    ] == "101"
    thin = queries.benchmark_levels(conn, bid, None, None, 2)
    assert thin[0]["date"] == "2024-01-01" and thin[-1]["date"] == "2024-01-05" and len(thin) <= 4
    sub = queries.benchmark_levels(conn, bid, date(2024, 1, 3), date(2024, 1, 4), 100)
    assert [p["date"] for p in sub] == ["2024-01-03", "2024-01-04"]
    assert queries.benchmark_levels(conn, bid, date(2030, 1, 1), None, 100) == []


def test_research_and_activity_summaries_on_an_empty_research_store(env):
    conn, _ = env
    assert queries.research_health(conn) == {
        "backtests": 0, "experiments": 0, "validation_reports": 0, "validation_reports_passed": 0,
        "latest_run": None}  # fmt: skip
    assert queries.backtests(conn) == {"items": [], "total": 0, "limit": 50, "offset": 0}
    assert queries.backtest(conn, 1) is None
    assert queries.corporate_action_health(conn) == {
        "actions_by_status": {"ok": 1}, "resolutions_by_status": {}}  # fmt: skip
    conn.execute("INSERT INTO partition_load (source,dataset,partition,status,at) VALUES"
                 " ('nse','bhav','2025-06-09','loaded',%s)", (NOW,))  # fmt: skip
    act = queries.ingestion_activity(conn, 5)
    assert act["total"] == 1 and (act["limit"], act["offset"]) == (5, 0)
    row = act["items"][0]
    assert (
        row["partition"] == "2025-06-09"
        and row["status"] == "loaded"
        and row["superseded"] is False
    )


def test_a_backtest_run_is_listed_and_returned_in_full(env):
    conn, _ = env
    conn.execute(
        "INSERT INTO backtest_run (strategy_id,strategy_version,params,params_hash,code_version,"
        "reader_mode,config,cost_model,adjustment_versions,provisional_events,unapplied_events,"
        "blocked_instruments,unmodelled_events,accounting_complete,dividends_received,metrics,"
        "result_hash,created_at,ledger_reconciled,reconciliation,pnl) VALUES ('s','1','{}','ph','c','research',"
        "'{}','{}','{}','[]','[]','[]','[]',true,12.50,'{\"sharpe\": 1.2}','rh',%s,true,'{}','{}')", (NOW,))  # fmt: skip
    lst = queries.backtests(conn)["items"]
    assert lst[0]["strategy_id"] == "s" and lst[0]["metrics"] == {"sharpe": 1.2}
    assert (
        queries.backtests(conn, 1, 1)["items"] == [] and queries.backtests(conn, 1, 1)["total"] == 1
    )
    full = queries.backtest(conn, lst[0]["run_id"])
    assert full["dividends_received"] == "12.50" and full["accounting_complete"] is True
    assert full["created_at"].startswith("2026-11-07") and full["params_hash"] == "ph"
    r = queries.research_health(conn)
    assert r["backtests"] == 1 and r["latest_run"]["strategy_id"] == "s"


def test_a_superseded_quarantine_never_reads_as_a_live_problem(conn):
    migrate(conn)
    for status in ("quarantined", "loaded"):
        conn.execute("INSERT INTO partition_load (source,dataset,partition,status,at) VALUES"
                     " ('nse','bhav','2022-08-08',%s,%s)", (status, NOW))  # fmt: skip
    conn.execute(
        "INSERT INTO partition_load (source,dataset,partition,status,at) VALUES"
        " ('nse','bhav','2022-08-09','quarantined',%s)",
        (NOW,),
    )  # still quarantined
    page = queries.ingestion_activity(conn, 10)["items"]
    by = {(r["partition"], r["status"]): r for r in page}
    old = by[("2022-08-08", "quarantined")]
    assert old["superseded"] is True and old["current_status"] == "loaded"
    assert by[("2022-08-08", "loaded")]["superseded"] is False
    live = by[("2022-08-09", "quarantined")]
    assert live["superseded"] is False and live["current_status"] == "quarantined"
    assert [r["id"] for r in queries.ingestion_activity(conn, 1, 1)["items"]] == [2]  # paging


def test_search_treats_percent_and_underscore_literally(env):
    conn, _ = env
    assert queries.search_instruments(conn, "%") == []
    assert queries.search_instruments(conn, "_") == []
    assert queries.search_instruments(conn, "X_Z") == []
    assert [r["symbol"] for r in queries.search_instruments(conn, "XYZ")] == ["XYZ"]
