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
    assert [p["date"] for p in full["levels"]] == [f"2024-01-0{d}" for d in range(1, 6)]
    assert full["levels"][0]["level"] == "101"
    assert (full["total_observations"], full["returned"], full["downsampled"]) == (5, 5, False)
    assert full["method"] == "all observations"
    sub = queries.benchmark_levels(conn, bid, date(2024, 1, 3), date(2024, 1, 4), 100)
    assert [p["date"] for p in sub["levels"]] == ["2024-01-03", "2024-01-04"]
    assert queries.benchmark_levels(conn, bid, date(2030, 1, 1), None, 100)["levels"] == []


def test_downsampling_keeps_every_peak_and_trough_and_the_ends(conn):
    migrate(conn)
    bid = register(
        conn, name="X", provider="p", index_symbol="X", return_type="PRICE", methodology_version="m"
    )
    days = [date(2020, 1, 1) + __import__("datetime").timedelta(days=i) for i in range(1000)]
    base = [D(100 + (i % 7)) for i in range(1000)]
    base[333], base[777] = D(900), D(1)  # a spike and a crash that every-Nth sampling would hide
    ingest(
        conn,
        bid,
        list(zip(days, base, strict=True)),
        source="s",
        source_timestamp=NOW,
        raw_hash="h",
        now=NOW,
    )
    r = queries.benchmark_levels(conn, bid, None, None, 100)
    assert r["downsampled"] and r["total_observations"] == 1000 and r["returned"] < 1000
    assert r["method"] == "min-max per bucket (extremes preserved)"
    got = {p["date"]: p["level"] for p in r["levels"]}
    assert got[days[333].isoformat()] == "900" and got[days[777].isoformat()] == "1"
    assert days[0].isoformat() in got and days[-1].isoformat() in got
    ordered = [p["date"] for p in r["levels"]]
    assert ordered == sorted(ordered) and len(set(ordered)) == len(ordered)
    assert r["returned"] <= 100 + 2


def test_research_and_activity_summaries_on_an_empty_research_store(env):
    conn, _ = env
    assert queries.research_health(conn) == {
        "backtests": 0, "experiments": 0, "validation_reports": 0, "validation_reports_passed": 0,
        "latest_run": None}  # fmt: skip
    assert queries.backtests(conn) == {"items": [], "total": 0, "limit": 50, "offset": 0}
    assert queries.backtest(conn, 1) is None
    ca = queries.corporate_action_health(conn)
    assert ca["actions_by_status"] == {"ok": 1} and ca["resolutions_by_status"] == {}
    assert (ca["total_events"], ca["verified"], ca["pending_review"]) == (1, 1, 0)
    assert (ca["review_without_any_resolution"], ca["provisional_adjustments"]) == (0, 0)
    conn.execute("INSERT INTO partition_load (source,dataset,partition,status,at) VALUES"
                 " ('nse','bhav','2025-06-09','loaded',%s)", (NOW,))  # fmt: skip
    act = queries.ingestion_activity(conn, 5)
    assert act["total"] == 1 and (act["limit"], act["offset"]) == (5, 0)
    row = act["items"][0]
    assert row["partition"] == "2025-06-09" and row["status"] == "loaded"
    assert set(row) == {"id", "source", "dataset", "partition", "status", "at"}


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


def test_each_date_shows_only_its_latest_load_so_an_old_failure_or_no_file_never_lingers(conn):
    migrate(conn)
    for day, status in (
        ("2022-08-08", "quarantined"),
        ("2022-08-08", "loaded"),  # fixed later: the quarantine is gone from the list
        ("2022-08-09", "quarantined"),  # still quarantined: stays, as a live problem
        ("2026-11-13", "not_published"),  # the file was not out yet ...
        ("2026-11-13", "not_published"),  # ... retried, still not out ...
        ("2026-11-13", "loaded"),  # ... then it was
    ):
        conn.execute("INSERT INTO partition_load (source,dataset,partition,status,at) VALUES"
                     " ('nse','bhav',%s,%s,%s)", (day, status, NOW))  # fmt: skip
    act = queries.ingestion_activity(conn, 10)
    assert act["total"] == 3
    assert [(r["partition"], r["status"]) for r in act["items"]] == [
        ("2026-11-13", "loaded"),
        ("2022-08-09", "quarantined"),
        ("2022-08-08", "loaded"),
    ]  # newest event first
    assert [r["partition"] for r in queries.ingestion_activity(conn, 1, 1)["items"]] == [
        "2022-08-09"
    ]
    assert queries.ingestion_activity(conn, 5, 3)["items"] == []
    conn.execute("INSERT INTO partition_load (source,dataset,partition,status,at) VALUES"
                 " ('kite','bhav','2022-08-09','loaded',%s)", (NOW,))  # fmt: skip
    assert queries.ingestion_activity(conn, 10)["total"] == 4  # a different source is its own row


def test_search_treats_percent_and_underscore_literally(env):
    conn, _ = env
    assert queries.search_instruments(conn, "%") == []
    assert queries.search_instruments(conn, "_") == []
    assert queries.search_instruments(conn, "X_Z") == []
    assert [r["symbol"] for r in queries.search_instruments(conn, "XYZ")] == ["XYZ"]


def test_corporate_action_summary_separates_pending_provisional_and_decided(env):
    conn, iid = env
    for ex, kind in (("2025-01-01", "rights"), ("2025-02-01", "demerger"), ("2025-03-01", "buy")):
        conn.execute(
            "INSERT INTO corporate_action (instrument_id,ex_date,kind,status,subject,knowledge_time,"
            "knowledge_time_source,source,raw_checksum,ingested_at) VALUES (%s,%s,%s,'review','t',%s,"
            "'ex_date_proxy','nse','x',%s)", (iid, ex, kind, NOW, NOW))  # fmt: skip
    conn.execute(
        "INSERT INTO action_resolution (instrument_id,ex_date,kind,treatment,factor,method,inputs,note,"
        "resolved_by,resolved_at,status) VALUES (%s,'2025-01-01','rights','factor',0.9,'rights','{}','n','me',%s,"
        "'provisional')", (iid, NOW))  # fmt: skip
    conn.execute(
        "INSERT INTO action_resolution (instrument_id,ex_date,kind,treatment,method,inputs,note,resolved_by,"
        "resolved_at,status,source_type,source_url,confirmed_by,confirmed_at) VALUES (%s,'2025-02-01',"
        "'demerger','ignore','demerger','{}','n','me',%s,'no_adjustment_verified','filing','u','me',%s)", (iid, NOW, NOW))  # fmt: skip
    ca = queries.corporate_action_health(conn)
    assert (ca["total_events"], ca["verified"], ca["pending_review"]) == (4, 1, 3)
    assert ca["review_without_any_resolution"] == 1  # only the 'buy' has no decision at all
    assert (
        ca["provisional_adjustments"],
        ca["no_adjustment_verified"],
        ca["ignored_with_reason"],
    ) == (1, 1, 0)


def test_known_holidays_are_the_days_with_no_published_file(conn):
    migrate(conn)
    for part, status in (
        ("2025-01-26", "not_published"),
        ("2025-01-27", "loaded"),
        ("2025-01-28", "not_published"),
    ):
        conn.execute("INSERT INTO partition_load (source,dataset,partition,status,at) VALUES"
                     " ('nse','bhav',%s,%s,%s)", (part, status, NOW))  # fmt: skip
    conn.execute(
        "INSERT INTO partition_load (source,dataset,partition,status,at) VALUES"
        " ('nse','bhav','2025-01-28','loaded',%s)",
        (NOW,),
    )  # later published after all
    assert queries.known_holidays(conn) == frozenset({date(2025, 1, 26)})


def test_indicator_catalogue_describes_every_indicator():
    cat = queries.indicator_catalog()
    names = [i["name"] for i in cat]
    assert names[:3] == ["sma", "ema", "wma"] and len(names) == 14
    rsi = next(i for i in cat if i["name"] == "rsi")
    assert rsi["pane"] == "pane" and rsi["levels"] == ["30", "70"]
    assert rsi["params"] == [
        {
            "key": "length",
            "label": "Length",
            "default": "14",
            "min": "1",
            "max": "200",
            "integer": True,
        }
    ]
    bb = next(i for i in cat if i["name"] == "bb")
    assert [p["key"] for p in bb["params"]] == ["length", "mult"] and bb["params"][1][
        "integer"
    ] is False
    assert [o["key"] for o in bb["outputs"]] == ["upper", "basis", "lower"]
    assert next(i for i in cat if i["name"] == "obv")["params"] == []


def seed_closes(conn, iid, closes):
    from datetime import timedelta

    for i, c in enumerate(closes):
        d = date(2025, 1, 1) + timedelta(days=i)
        conn.execute(
            "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,dataset_version,"
            "ingested_at) VALUES (%s,%s,%s,%s,%s,%s,100,'nse',1,%s)",
            (iid, ts(d), c, c + 1, c - 1, c, NOW))  # fmt: skip


def test_indicators_are_warmed_up_on_the_full_history_and_returned_for_the_window(env):
    conn, iid = env
    seed_closes(conn, iid, [100 + i for i in range(40)])  # 2025-01-01 .. 2025-02-09, rising
    full = queries.indicator_series(
        conn, iid, date(2025, 1, 1), date(2025, 2, 9), "none", ["sma:5"]
    )
    late = queries.indicator_series(
        conn, iid, date(2025, 2, 1), date(2025, 2, 9), "none", ["sma:5", "rsi:3"]
    )
    assert late["dates"][0] == "2025-02-01" and len(late["dates"]) == 9
    sma_full = next(o for o in full["indicators"][0]["outputs"])["values"]
    sma_late = late["indicators"][0]["outputs"][0]["values"]
    assert sma_full[0] is None  # warm-up inside the full window
    assert (
        sma_late[0] is not None and sma_late[0] == sma_full[-9]
    )  # but warmed up before a later start
    assert late["indicators"][0]["spec"] == "sma:5" and late["indicators"][0]["label"] == "SMA 5"
    assert (
        late["indicators"][1]["label"] == "RSI 3"
        and late["indicators"][1]["outputs"][0]["values"][-1] == "100.0000"
    )
    assert late["adjust"] == "none" and late["adjustment_version"]
    bb = queries.indicator_series(conn, iid, date(2025, 2, 1), date(2025, 2, 9), "none", ["bb"])[
        "indicators"
    ][0]
    assert bb["label"] == "BB 20 2" and bb["params"] == {"length": "20", "mult": "2"}
    assert [o["key"] for o in bb["outputs"]] == ["upper", "basis", "lower"]
    empty = queries.indicator_series(conn, iid, date(2030, 1, 1), date(2030, 2, 1), "none", ["sma"])
    assert empty["dates"] == [] and empty["indicators"][0]["outputs"][0]["values"] == []


def test_weekly_indicators_are_computed_on_the_weekly_bars_over_the_whole_history(env):
    conn, iid = env
    seed_closes(conn, iid, [100 + i for i in range(40)])  # 2025-01-01 .. 2025-02-09
    weekly = queries.instrument_bars(conn, iid, date(2025, 1, 1), date(2025, 2, 9), "none", "1w")
    ind = queries.indicator_series(
        conn, iid, date(2025, 1, 1), date(2025, 2, 9), "none", ["sma:2"], "1w"
    )
    assert ind["dates"] == [
        b["date"] for b in weekly["bars"]
    ]  # one value per weekly candle, not per day
    values = ind["indicators"][0]["outputs"][0]["values"]
    closes = [D(b["close"]) for b in weekly["bars"]]
    assert values[0] is None and D(values[-1]) == (closes[-1] + closes[-2]) / 2
