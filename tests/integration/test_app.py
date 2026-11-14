import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from algo.data.benchmark import ingest, register, store_validation
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from tests.support.portal import open_app

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 7, tzinfo=UTC)
USES = {u: {"eligible": e, "blockers": []} for u, e in
        (("DAILY_RESEARCH", True), ("INTRADAY_RESEARCH", False), ("BENCHMARK_GATE", False))}  # fmt: skip


def write(p, doc):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc))


@pytest.fixture
def docs(tmp_path):
    write(tmp_path / "benchmark-release-1.1" / "release.json", {"release": "1.1"})
    a = tmp_path / "benchmark-audit-1.1"
    write(a / "benchmark_eligibility.json", {
        "benchmarks": {"B1_NIFTY200_GROSS_TRI": {"state": "RESEARCH_ELIGIBLE", "uses": USES}},
        "instrument_level_blocked_dates": []})  # fmt: skip
    write(
        a / "benchmark_unresolved_findings.json",
        {
            "findings": [
                {
                    "id": "U02",
                    "title": "hours",
                    "severity": "HIGH",
                    "status": "UNRESOLVED",
                    "category": "session-hours",
                    "detail": "hours are assumed",
                    "applies_to": ["ALL"],
                    "blocks": ["INTRADAY_RESEARCH"],
                },
                {
                    "id": "U01",
                    "title": "recovered",
                    "severity": "INFO",
                    "status": "RESOLVED",
                    "category": "session-evidence",
                    "detail": "resolved",
                    "applies_to": ["ALL"],
                    "blocks": [],
                },
                {
                    "id": "U07",
                    "title": "explained",
                    "severity": "LOW",
                    "status": "ACCEPTED_WITH_EVIDENCE",
                    "category": "methodology",
                    "detail": "accepted",
                    "applies_to": ["B1"],
                    "blocks": [],
                },
            ]
        },
    )
    write(a / "benchmark_alignment_report.json", {"benchmarks": {}})
    write(a / "session_reconciliation_report.json", {
        "calendar_version": {"sessions_file_sha256": "abc"}, "evidence": {"bhavcopy_range": ["a", "b"]},
        "observed_counts": {"CONFIRMED_REGULAR": 2},
        "observed": {"2024-01-01": ["CONFIRMED_REGULAR", ["B1", "B2"]],
                     "2024-01-02": ["WEEKDAY_RULE_PROVISIONAL", ["B1"]],
                     "2024-01-03": ["CONFIRMED_REGULAR", ["B2"]]},
        "missing_counts": {"B1_NIFTY200_GROSS_TRI": {"EXPECTED_CLOSED": 3}},
        "historical_session_hours": {"statement": "hours are assumed"}})  # fmt: skip
    return tmp_path


@pytest.fixture
def api(conn, pg_url, docs):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    iid = repo.add_instrument(x, "XYZ")
    for i, d in enumerate([date(2025, 6, 9), date(2025, 6, 10)]):
        conn.execute(
            "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,dataset_version,"
            "ingested_at) VALUES (%s,%s,1,2,1,%s,100,'nse',1,%s)",
            (iid, datetime(d.year, d.month, d.day, 3, 45, tzinfo=UTC), 1 + i, NOW))  # fmt: skip
    bid = register(conn, name="N200", provider="p", index_symbol="NIFTY 200",
                   return_type="TOTAL_RETURN", methodology_version="m")  # fmt: skip
    ingest(conn, bid, [(date(2024, 1, d), D(100 + d)) for d in (1, 2, 3)], source="s",
           source_timestamp=NOW, raw_hash="h", now=NOW)  # fmt: skip
    store_validation(conn, bid, report={"report_version": "2", "technical_validation_passed": True,
                                        "check_states": {}}, passed=True, normalized_sha256="n",
                     factsheet_sha256=None, unresolved=[], now=NOW)  # fmt: skip
    return TestClient(open_app(pg_url, docs)), iid, bid


def test_health_reports_the_database_and_what_is_not_configured(api):
    r = api[0].get("/api/health").json()
    assert r == {"api": "ok", "database": "ok", "redis": "not configured"}


def test_health_says_so_when_the_database_is_unreachable(docs):
    bad = TestClient(open_app("postgresql://nobody@127.0.0.1:1/none", docs))
    assert bad.get("/api/health").json()["database"].startswith("error")


def test_a_failed_job_shows_up_in_the_platform_verdict(api, conn):
    conn.execute(
        "INSERT INTO job_run (job, started_at, finished_at, status, attempts, detail)"
        " VALUES ('bhavcopy-daily', %s, %s, 'failed', 3, 'backfill_nse.py exited 1')", (NOW, NOW))  # fmt: skip
    texts = [r["text"] for r in api[0].get("/api/dashboard").json()["platform"]["reasons"]]
    assert any(
        t.startswith("bhavcopy-daily failed") and "backfill_nse.py exited 1" in t for t in texts
    )


def test_the_dashboard_lists_every_scheduled_job_with_when_it_last_ran(api, conn):
    from algo.jobs.registry import JOBS

    jobs = api[0].get("/api/dashboard").json()["jobs"]
    assert [j["name"] for j in jobs] == [j.name for j in JOBS]
    assert all(j["last_run"] is None for j in jobs)  # nothing has run yet: said as it is
    conn.execute(
        "INSERT INTO job_run (job, started_at, finished_at, status, attempts, detail)"
        " VALUES ('bhavcopy-daily', %s, %s, 'ok', 1, '')", (NOW, NOW))  # fmt: skip
    first = next(
        j for j in api[0].get("/api/dashboard").json()["jobs"] if j["name"] == "bhavcopy-daily"
    )
    assert first["last_run"]["status"] == "ok" and first["last_success_at"] == NOW.isoformat()


def test_the_dashboard_keeps_ingested_validated_and_eligible_apart(api):
    d = api[0].get("/api/dashboard").json()
    s = d["benchmarks"]["series"][0]
    assert d["benchmarks"]["release"] == "1.1" and d["benchmarks"]["gate"] == "disabled"
    assert (s["ingested"], s["technically_validated"], s["research_eligible_daily"],
            s["research_eligible_intraday"], s["benchmark_gate_eligible"]) == (True, True, True, False, False)  # fmt: skip
    assert s["eligibility_state"] == "RESEARCH_ELIGIBLE"
    assert d["strategies"]["persisted"] is False
    p = d["platform"]  # the verdict is computed from real signals, and says why
    assert p["status"] == "DOWN" and [r["level"] for r in p["reasons"]] == [
        "down",
        "attention",
        "attention",
    ]
    assert (
        p["reasons"][0]["text"].startswith("Price data is ") and "behind" in p["reasons"][0]["text"]
    )
    assert "No Kite data feed is connected" in p["reasons"][1]["text"]
    assert "scheduled jobs have never run" in p["reasons"][2]["text"]
    assert d["data"]["bars"] == 2 and d["research"]["backtests"] == 0
    assert d["system"]["redis"] == "not configured"


def test_without_release_artifacts_nothing_is_called_eligible(conn, pg_url, tmp_path):
    migrate(conn)
    bid = register(conn, name="N", provider="p", index_symbol="X", return_type="PRICE",
                   methodology_version="m")  # fmt: skip
    ingest(
        conn,
        bid,
        [(date(2024, 1, 1), D(1))],
        source="s",
        source_timestamp=NOW,
        raw_hash="h",
        now=NOW,
    )
    c = TestClient(open_app(pg_url, tmp_path))
    s = c.get("/api/dashboard").json()["benchmarks"]["series"][0]
    assert s["research_eligible_daily"] is False and s["benchmark_gate_eligible"] is False
    assert s["eligibility_state"].startswith("UNKNOWN") and s["technically_validated"] is False
    assert c.get("/api/benchmarks").json()["benchmarks"][0]["eligibility"] is None
    detail = c.get(f"/api/benchmarks/{bid}").json()
    assert (
        detail["findings"] == []
        and detail["session_calendar"] is None
        and detail["release"] is None
    )


def test_an_instruments_announced_future_actions_are_listed_apart_from_its_history(api, conn):
    c, iid, _ = api
    assert c.get(f"/api/instruments/{iid}").json()["upcoming"] == []
    conn.execute(
        "INSERT INTO corporate_action_upcoming (instrument_id, ex_date, kind, status, amount, subject, fetched_at)"
        " VALUES (%s,'2026-11-24','dividend','ok',7,'Interim Dividend - Rs 7 Per Share',%s),"
        " (%s,'2026-11-20','bonus','ok',NULL,'Bonus 1:1',%s)", (iid, NOW, iid, NOW))  # fmt: skip
    d = c.get(f"/api/instruments/{iid}").json()
    assert [(u["ex_date"], u["kind"]) for u in d["upcoming"]] == [
        ("2026-11-20", "bonus"),
        ("2026-11-24", "dividend"),
    ]  # soonest first
    assert d["upcoming"][1]["amount"] == "7" and d["actions"] == []  # not part of the history


def test_instrument_search_detail_and_bars(api):
    c, iid, _ = api
    assert [r["symbol"] for r in c.get("/api/instruments", params={"q": "xy"}).json()] == ["XYZ"]
    assert c.get("/api/instruments", params={"q": ""}).status_code == 422
    d = c.get(f"/api/instruments/{iid}").json()
    assert d["symbol"] == "XYZ" and d["bars"]["count"] == 2 and d["actions"] == []
    assert c.get("/api/instruments/999").status_code == 404
    b = c.get(
        f"/api/instruments/{iid}/bars", params={"start": "2025-06-01", "end": "2025-06-30"}
    ).json()
    assert b["adjust"] == "none" and [x["close"] for x in b["bars"]] == ["1", "2"]
    s = c.get(
        f"/api/instruments/{iid}/bars",
        params={"start": "2025-06-01", "end": "2025-06-30", "adjust": "split"},
    ).json()
    assert s["adjust"] == "split"
    assert (
        c.get(
            f"/api/instruments/{iid}/bars", params={"start": "2025-06-30", "end": "2025-06-01"}
        ).status_code
        == 422
    )
    assert (
        c.get(
            f"/api/instruments/{iid}/bars",
            params={"start": "2025-06-01", "end": "2025-06-30", "adjust": "magic"},
        ).status_code
        == 422
    )
    assert (
        c.get(
            "/api/instruments/999/bars", params={"start": "2025-06-01", "end": "2025-06-30"}
        ).status_code
        == 404
    )


def test_benchmark_list_detail_and_levels(api):
    c, _, bid = api
    lst = c.get("/api/benchmarks").json()
    assert lst["release"] == "1.1" and lst["gate"] == "disabled"
    assert lst["benchmarks"][0]["eligibility"]["state"] == "RESEARCH_ELIGIBLE"
    d = c.get(f"/api/benchmarks/{bid}").json()
    assert d["validations"][0]["technical_validation_passed"] is True
    assert [f["id"] for f in d["findings"]] == ["U02", "U01", "U07"] and d[
        "instrument_level_blocked_dates"
    ] == []
    assert d["session_calendar"]["historical_session_hours"] == "hours are assumed"
    cal = d["session_calendar"]
    assert [(r["code"], r["count"]) for r in cal["all_series"]] == [("CONFIRMED_REGULAR", 2)]
    mine = cal["this_series"]
    assert mine["series"] == "B1_NIFTY200_GROSS_TRI"
    assert [(r["code"], r["count"]) for r in mine["observed"]] == [
        ("CONFIRMED_REGULAR", 1),
        ("WEEKDAY_RULE_PROVISIONAL", 1),
    ]
    assert [(r["code"], r["count"]) for r in mine["missing"]] == [("EXPECTED_CLOSED", 3)]
    assert cal["listed_special_sessions"] is None  # no sessions file frozen with this release
    assert c.get("/api/benchmarks/99").status_code == 404
    reply = c.get(f"/api/benchmarks/{bid}/levels").json()
    assert reply["total_observations"] == 3
    assert c.get(f"/api/benchmarks/{bid}/levels", params={"max_points": 2}).status_code == 422
    assert c.get("/api/benchmarks/99/levels").status_code == 404


def test_the_dashboard_judges_freshness_by_sessions_with_an_injected_clock(api, pg_url, docs):
    from algo.core.clock import SimClock

    sunday = SimClock(datetime(2026, 11, 8, 4, 51, tzinfo=UTC))
    c = TestClient(open_app(pg_url, docs, clock=sunday))
    f = c.get("/api/dashboard").json()["data"]["freshness"]
    assert (
        f["latest_bar_session"] == "2025-06-10"
        and f["status"] == "BEHIND"
        and f["sessions_behind"] > 100
    )
    assert f["expected_latest_session"] == "2026-11-06" and f["next_session"] == "2026-11-09"


def test_session_properties_appear_when_the_sessions_file_is_the_frozen_one(
    api, pg_url, docs, tmp_path
):
    import hashlib

    sess = tmp_path / "exchange_sessions.json"
    sess.write_text(
        json.dumps(
            {"sessions": [{"kind_status": "UNCONFIRMED (x)", "hours_status": "UNKNOWN (y)"}]}
        )
    )
    write(
        docs / "benchmark-release-1.1" / "release.json",
        {
            "release": "1.1",
            "calendar_inputs": {
                "sessions_file_sha256": hashlib.sha256(sess.read_bytes()).hexdigest()
            },
        },
    )
    c = TestClient(open_app(pg_url, docs, sessions_file=sess))
    props = c.get(f"/api/benchmarks/{api[2]}").json()["session_calendar"]["listed_special_sessions"]
    assert props == {
        "listed_sessions": 1,
        "kind": {"UNCONFIRMED": 1},
        "opening_time": {"UNKNOWN": 1},
        "closing_time": {"UNKNOWN": 1},
    }


def test_an_empty_database_has_no_freshness(conn, pg_url, docs):
    migrate(conn)
    assert (
        TestClient(open_app(pg_url, docs)).get("/api/dashboard").json()["data"]["freshness"] is None
    )


def test_backtests_and_system_activity(api):
    c, _, bid = api
    assert c.get("/api/backtests").json() == {"items": [], "total": 0, "limit": 50, "offset": 0}
    assert c.get("/api/backtests/1").status_code == 404
    a = c.get("/api/system/activity").json()
    assert a["jobs"]["persisted"] is False and a["backtests"] == []
    assert (
        a["validations"][0]["benchmark_id"] == bid
        and a["validations"][0]["latest"]["validation_id"] == 1
    )


def test_the_validation_list_tolerates_a_benchmark_with_no_validation(conn, pg_url, docs):
    migrate(conn)
    register(
        conn, name="N", provider="p", index_symbol="X", return_type="PRICE", methodology_version="m"
    )
    a = TestClient(open_app(pg_url, docs)).get("/api/system/activity").json()
    assert a["validations"] == [{"benchmark_id": 1, "name": "N", "latest": None}]


def test_cors_allows_only_the_console_origin_and_get(api):
    c = api[0]
    ok = c.get("/api/health", headers={"Origin": "http://localhost:3000"})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:3000"
    other = c.get("/api/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in other.headers
    assert c.post("/api/health").status_code == 405


def test_a_stored_backtest_is_listed_and_returned_by_id(api, conn):
    c = api[0]
    conn.execute(
        "INSERT INTO backtest_run (strategy_id,strategy_version,params,params_hash,code_version,"
        "reader_mode,config,cost_model,adjustment_versions,provisional_events,unapplied_events,"
        "blocked_instruments,unmodelled_events,accounting_complete,dividends_received,metrics,"
        "result_hash,created_at,ledger_reconciled,reconciliation,pnl) VALUES ('s','1','{}','ph','c',"
        "'research','{}','{}','{}','[]','[]','[]','[]',true,0,'{}','rh',%s,true,'{}','{}')", (NOW,))  # fmt: skip
    run = c.get("/api/backtests").json()["items"][0]
    assert run["strategy_id"] == "s" and run["ledger_reconciled"] is True
    full = c.get(f"/api/backtests/{run['run_id']}").json()
    assert full["result_hash"] == "rh" and full["reader_mode"] == "research"


def test_a_backtest_report_pairs_the_stored_trades_into_round_trips(api, conn):
    c, iid, _ = api
    assert c.get("/api/backtests/1/report").status_code == 404
    run_id = conn.execute(
        "INSERT INTO backtest_run (strategy_id,strategy_version,params,params_hash,code_version,"
        "reader_mode,config,cost_model,adjustment_versions,provisional_events,unapplied_events,"
        "blocked_instruments,unmodelled_events,accounting_complete,dividends_received,metrics,"
        "result_hash,created_at,ledger_reconciled,reconciliation,pnl) VALUES ('s','1','{}','ph','c',"
        '\'research\',\'{"initial_cash": "10000", "start": "2024-01-01", "end": "2024-03-01"}\','
        "'{}','{}','[]','[]','[]','[]',true,0,'{}','rh',%s,true,'{}','{}') RETURNING run_id",
        (NOW,),  # fmt: skip
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO backtest_trade (run_id,seq,day,instrument_id,side,qty,price,cost) VALUES "
        "(%s,1,'2024-01-01',%s,'BUY',10,100,2),(%s,2,'2024-02-01',%s,'SELL',10,130,3)",
        (run_id, iid, run_id, iid),
    )
    conn.execute(
        "INSERT INTO backtest_equity VALUES (%s,'2024-01-01',10000),(%s,'2024-03-01',10295)",
        (run_id, run_id),
    )
    r = c.get(f"/api/backtests/{run_id}/report").json()
    trip = r["round_trips"][0]
    assert (trip["symbol"], trip["qty"], trip["gross"], trip["charges"], trip["net"]) == (
        "XYZ",
        "10",
        "300",
        "5",
        "295",
    )
    assert (r["headline"]["final"], r["headline"]["change"]) == ("10295", "295")
    assert r["by_stock"][0]["net"] == "295" and r["start"] == "2024-01-01"
    assert "is not loaded" in r["benchmark"]["note"] and r["benchmark"]["curve"] == []
    assert (
        r["study"] is None and r["summary"]["cost_drag"] == "0.0167"
    )  # 5 of the 300 made before charges

    from algo.backtest.validation import registry
    from algo.research import study_jobs

    exp = registry.register(conn, name="S", strategy_id="s", hypothesis="h", style="long_only", param_ranges={},
                            holdout=(date(2024, 6, 1), date(2024, 7, 1)), now=NOW, study={})  # fmt: skip
    study_jobs.save_trial(conn, exp, {"a": 1}, "h", "DONE", NOW, backtest_run=run_id)
    assert c.get(f"/api/backtests/{run_id}/report").json()["study"] == {
        "experiment_id": exp,
        "name": "S",
    }

    from algo.data.benchmark import DEFAULT_BENCHMARK

    bid = register(conn, name=DEFAULT_BENCHMARK, provider="p", index_symbol="N200TRI",
                   return_type="TOTAL_RETURN", methodology_version="m")  # fmt: skip
    levels = [(date(2024, 1, 1), D(1000)), (date(2024, 3, 1), D(1100))]
    ingest(conn, bid, levels, source="s", source_timestamp=NOW, raw_hash="h2", now=NOW)
    assert (
        "no passing validation"
        in c.get(f"/api/backtests/{run_id}/report").json()["benchmark"]["note"]
    )
    store_validation(conn, bid, report={"report_version": "2", "technical_validation_passed": True,
                                        "check_states": {}}, passed=True, normalized_sha256="n",
                     factsheet_sha256=None, unresolved=[], now=NOW)  # fmt: skip
    b = c.get(f"/api/backtests/{run_id}/report").json()["benchmark"]
    assert (b["name"], b["note"], b["return"], b["final"]) == (
        DEFAULT_BENCHMARK,
        None,
        "0.1000",
        "11000",
    )
    assert b["strategy_return"] == "0.0295" and [p["level"] for p in b["curve"]] == [
        "10000",
        "11000",
    ]


def test_every_database_session_is_read_only_and_time_limited(pg_url, conn):
    import psycopg

    from algo.api.app import DB_OPTIONS

    migrate(conn)
    with psycopg.connect(pg_url, options=DB_OPTIONS) as ro:
        assert ro.execute("SELECT 1").fetchone() == (1,)
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            ro.execute("CREATE TABLE intruder (x int)")
        ro.rollback()
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            ro.execute(
                "INSERT INTO partition_load (source,dataset,partition,status) VALUES ('a','b','2024-01-01','loaded')"
            )
        ro.rollback()
        assert ro.execute("SHOW statement_timeout").fetchone() == ("15s",)


def test_responses_carry_security_headers_and_are_never_cached(api):
    r = api[0].get("/api/health")
    assert (
        r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    )
    assert (
        r.headers["referrer-policy"] == "no-referrer" and r.headers["cache-control"] == "no-store"
    )
    assert "geolocation=()" in r.headers["permissions-policy"]
    assert api[0].get("/api/instruments/999").headers["x-frame-options"] == "DENY"  # errors too


def test_interactive_docs_are_off_unless_asked_for(api, pg_url, docs):
    c = api[0]
    assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404
    on = TestClient(open_app(pg_url, docs, interactive_docs=True))
    assert on.get("/docs").status_code == 200 and on.get("/openapi.json").status_code == 200


def test_inputs_are_bounded(api):
    c, iid, _ = api
    assert c.get("/api/instruments", params={"q": "x" * 65}).status_code == 422
    assert c.get("/api/instruments", params={"q": "x" * 64}).status_code == 200
    assert c.get("/api/instruments", params={"q": "x", "limit": 101}).status_code == 422
    wide = {"start": "1900-01-01", "end": "2100-01-01"}
    assert c.get(f"/api/instruments/{iid}/bars", params=wide).status_code == 422
    ok = {"start": "1990-01-01", "end": "2026-01-01"}
    assert c.get(f"/api/instruments/{iid}/bars", params=ok).status_code == 200
    assert c.get("/api/backtests", params={"limit": 201}).status_code == 422
    assert c.get("/api/backtests", params={"offset": -1}).status_code == 422
    assert c.get("/api/system/activity", params={"limit": 0}).status_code == 422


def test_a_wildcard_search_does_not_dump_the_universe(api):
    c = api[0]
    assert c.get("/api/instruments", params={"q": "%"}).json() == []


def test_activity_is_paged_and_lists_only_each_partitions_latest_load(api, conn):
    c = api[0]
    for day, status in (
        ("2022-08-08", "quarantined"),
        ("2022-08-08", "loaded"),
        ("2022-08-09", "loaded"),
    ):
        conn.execute("INSERT INTO partition_load (source,dataset,partition,status,at) VALUES"
                     " ('nse','bhav',%s,%s,%s)", (day, status, NOW))  # fmt: skip
    page = c.get("/api/system/activity", params={"limit": 1}).json()["ingestion"]
    assert page["total"] == 2 and [r["partition"] for r in page["items"]] == ["2022-08-09"]
    rest = c.get("/api/system/activity", params={"limit": 1, "offset": 1}).json()["ingestion"]
    assert [(r["partition"], r["status"]) for r in rest["items"]] == [("2022-08-08", "loaded")]


def test_the_activity_page_names_each_benchmark_and_starts_with_an_empty_paged_log(api):
    c, _, _ = api
    a = c.get("/api/system/activity").json()
    assert a["validations"][0]["name"] == "N200"
    assert a["ingestion"] == {"items": [], "total": 0, "limit": 25, "offset": 0}


def test_the_indicator_catalogue_and_series_endpoints(api):
    c, iid, _ = api
    cat = c.get("/api/indicators").json()["indicators"]
    assert len(cat) == 14 and cat[0]["name"] == "sma"
    r = c.get(
        f"/api/instruments/{iid}/indicators",
        params={"start": "2025-06-01", "end": "2025-06-30", "names": "sma:2,rsi"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["dates"] == ["2025-06-09", "2025-06-10"] and [
        i["spec"] for i in body["indicators"]
    ] == ["sma:2", "rsi:14"]
    assert body["indicators"][0]["outputs"][0]["values"] == [None, "1.5000"]


def test_indicator_requests_are_validated(api):
    c, iid, _ = api
    ok = {"start": "2025-06-01", "end": "2025-06-30", "names": "sma"}
    url = f"/api/instruments/{iid}/indicators"
    assert c.get(url, params={**ok, "names": "nope"}).json()["detail"] == "unknown indicator 'nope'"
    assert c.get(url, params={**ok, "names": "rsi:0"}).status_code == 422
    assert c.get(url, params={**ok, "names": ","}).status_code == 422  # nothing asked for
    assert c.get(url, params={**ok, "names": ",".join(["sma"] * 13)}).status_code == 422  # too many
    assert c.get(url, params={**ok, "names": "x" * 401}).status_code == 422
    assert c.get(url, params={**ok, "start": "2025-07-01"}).status_code == 422
    assert c.get(url, params={**ok, "start": "1900-01-01", "end": "2100-01-01"}).status_code == 422
    assert c.get(url, params={**ok, "adjust": "magic"}).status_code == 422
    assert c.get("/api/instruments/999/indicators", params=ok).status_code == 404


def put_minutes(conn, iid, day, n, close0=100):
    """n consecutive Kite minutes from 09:15 IST on `day`: open=close0+i, close=close0+i+0.5, volume 10."""
    for i in range(n):
        conn.execute(
            "INSERT INTO bar_1m (instrument_id,ts,open,high,low,close,volume,source,adjusted_through,"
            "dataset_version,ingested_at) VALUES (%s,%s,%s,%s,%s,%s,10,'kite',%s,1,%s)",
            (iid, datetime(day.year, day.month, day.day, 3, 45 + i, tzinfo=UTC), close0 + i,
             close0 + i + 1, close0 + i - 1, close0 + i + D("0.5"), date(2026, 11, 1), NOW))  # fmt: skip


def test_intraday_bars_come_from_the_stored_minutes_with_a_utc_time_and_the_ist_date(api, conn):
    c, iid, _ = api
    put_minutes(conn, iid, date(2025, 6, 9), 7)
    q = {"start": "2025-06-09", "end": "2025-06-09", "timeframe": "5m"}
    b = c.get(f"/api/instruments/{iid}/bars", params=q).json()
    assert b["timeframe"] == "5m" and b["adjust"] == "none" and b["clean"] is True
    assert [
        (x["time"], x["date"], x["open"], x["high"], x["low"], x["close"], x["volume"])
        for x in b["bars"]
    ] == [
        (1749440700, "2025-06-09", "100", "105", "99", "104.5", "50"),  # 09:15-09:19 IST
        (
            1749441000,
            "2025-06-09",
            "105",
            "107",
            "104",
            "106.5",
            "20",
        ),  # 09:20-09:21 only: not padded
    ]
    one = c.get(f"/api/instruments/{iid}/bars", params={**q, "timeframe": "1m"}).json()
    assert len(one["bars"]) == 7 and one["bars"][0]["time"] == 1749440700
    sp = c.get(f"/api/instruments/{iid}/bars", params={**q, "adjust": "split"}).json()
    assert sp["adjust"] == "split" and sp["bars"][0]["factor"] == "1"
    assert (
        c.get(
            f"/api/instruments/{iid}/bars", params={**q, "start": "2025-06-10", "end": "2025-06-10"}
        ).json()["bars"]
        == []
    )


def test_the_daily_timeframe_is_the_default_and_still_has_no_time_field(api):
    c, iid, _ = api
    b = c.get(
        f"/api/instruments/{iid}/bars", params={"start": "2025-06-01", "end": "2025-06-30"}
    ).json()
    assert b["timeframe"] == "1d" and all("time" not in x for x in b["bars"])


def test_intraday_requests_are_refused_when_unsupported_or_too_wide(api):
    c, iid, _ = api
    url = f"/api/instruments/{iid}/bars"
    base = {"start": "2025-06-01", "end": "2025-06-09", "timeframe": "1m"}
    assert c.get(url, params={**base, "timeframe": "2m"}).status_code == 422  # not a timeframe
    assert (
        c.get(url, params={**base, "adjust": "total_return"}).status_code == 422
    )  # no dividends on minutes
    assert (
        c.get(url, params={**base, "end": "2025-07-15"}).status_code == 422
    )  # 1m: at most 31 days
    assert c.get(url, params={**base, "timeframe": "5m", "end": "2025-07-15"}).status_code == 200
    assert c.get(url, params={**base, "timeframe": "1h", "end": "2027-07-01"}).status_code == 422


def test_weekly_and_monthly_bars_are_built_from_the_daily_series_with_every_price_basis(api):
    c, iid, _ = api
    url = f"/api/instruments/{iid}/bars"
    for tf in ("1w", "1mo"):
        for adjust in ("none", "split", "total_return"):
            b = c.get(
                url,
                params={
                    "start": "2025-06-01",
                    "end": "2025-06-30",
                    "timeframe": tf,
                    "adjust": adjust,
                },
            ).json()
            assert b["timeframe"] == tf and b["adjust"] == adjust
            assert [
                (x["date"], x["open"], x["high"], x["low"], x["close"], x["volume"])
                for x in b["bars"]
            ] == [("2025-06-09", "1", "2", "1", "2", "200")]
            assert "time" not in b["bars"][0]  # a daily-style axis, like 1D


def test_the_wider_minute_and_hour_timeframes_are_accepted_with_their_own_range_caps(api, conn):
    c, iid, _ = api
    put_minutes(conn, iid, date(2025, 6, 9), 7)
    url = f"/api/instruments/{iid}/bars"
    q = {"start": "2025-06-09", "end": "2025-06-09"}
    three = c.get(url, params={**q, "timeframe": "3m"}).json()["bars"]
    assert [x["volume"] for x in three] == ["30", "30", "10"]
    assert c.get(url, params={**q, "timeframe": "4h"}).json()["bars"][0]["volume"] == "70"
    assert (
        c.get(url, params={**q, "timeframe": "10m", "end": "2026-02-01"}).status_code == 200
    )  # 237 days <= 248
    assert (
        c.get(url, params={**q, "timeframe": "10m", "end": "2026-02-15"}).status_code == 422
    )  # 251 days > 248


def _filing(conn, iid, seq, end, basis, filed, facts):
    fid = conn.execute(
        "INSERT INTO fundamental_filing (symbol,isin,instrument_id,seq_number,period_start,period_end,basis,audited,bank,"
        "filed_at,rounding,xbrl_url,raw_sha256,ingested_at) VALUES ('XYZ','INX',%s,%s,%s,%s,%s,true,false,%s,'Crores','u','h',%s)"
        " RETURNING filing_id",
        (iid, seq, end - timedelta(days=89), end, basis, filed, NOW),
    ).fetchone()[0]
    for scope, metric, value in facts:
        conn.execute(
            "INSERT INTO fundamental_fact VALUES (%s,%s,%s,%s)", (fid, metric, scope, value)
        )


def test_fundamentals_are_the_latest_filing_per_quarter_for_the_chosen_basis(api, conn):
    c, iid, _ = api
    empty = {"instrument_id": iid, "symbol": "XYZ", "bases": [], "basis": None, "periods": []}
    assert c.get(f"/api/instruments/{iid}/fundamentals").json() == empty
    assert c.get("/api/instruments/999/fundamentals").status_code == 404
    d = datetime(2026, 1, 1, tzinfo=UTC)
    q4, q3 = date(2025, 12, 31), date(2025, 9, 30)
    _filing(
        conn,
        iid,
        "1",
        q4,
        "CONSOLIDATED",
        d,
        [("QUARTER", "Income", D(10)), ("INSTANT", "Assets", D(500)), ("QUARTER", "pat", D(1))],
    )
    _filing(
        conn, iid, "2", q4, "CONSOLIDATED", d + timedelta(days=30), [("QUARTER", "Income", D(12))]
    )  # restated
    _filing(conn, iid, "3", q3, "CONSOLIDATED", d - timedelta(days=90), [("YTD", "Income", D(7))])
    _filing(conn, iid, "4", q4, "STANDALONE", d, [("QUARTER", "Income", D(3))])
    r = c.get(f"/api/instruments/{iid}/fundamentals").json()
    assert (r["bases"], r["basis"]) == (["CONSOLIDATED", "STANDALONE"], "CONSOLIDATED")
    assert [p["period_end"] for p in r["periods"]] == ["2025-12-31", "2025-09-30"]  # newest first
    assert (
        r["periods"][0]["quarter"] == {"Income": "12"} and r["periods"][0]["instant"] == {}
    )  # the restated filing wins
    assert r["periods"][1]["ytd"] == {"Income": "7"} and r["periods"][0]["rounding"] == "Crores"
    s = c.get(
        f"/api/instruments/{iid}/fundamentals", params={"basis": "STANDALONE", "quarters": 1}
    ).json()
    assert s["basis"] == "STANDALONE" and s["periods"][0]["quarter"] == {"Income": "3"}
    assert c.get(f"/api/instruments/{iid}/fundamentals", params={"basis": "X"}).status_code == 422


def test_ratios_are_computed_from_filings_with_a_year_ago_and_a_history_and_withheld_after_a_split(
    api, conn
):
    c, iid, _ = api
    assert c.get("/api/instruments/999/ratios").status_code == 404
    assert c.get(f"/api/instruments/{iid}/ratios").json()["ratios"] == []
    assert c.get(f"/api/instruments/{iid}/ratios", params={"basis": "X"}).status_code == 422
    ends = [
        date(2025, 3, 31),
        date(2025, 6, 30),
        date(2025, 9, 30),
        date(2025, 12, 31),
        date(2026, 3, 31),
        date(2026, 6, 30),
    ]
    for i, end in enumerate(ends):
        facts = [
            ("QUARTER", "RevenueFromOperations", D(1000 + 100 * i)),
            ("QUARTER", "ProfitLossForPeriod", D(100 + 10 * i)),
            (
                "QUARTER",
                "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
                D(10 + i),
            ),
            ("QUARTER", "PaidUpValueOfEquityShareCapital", D(1000)),
            ("QUARTER", "FaceValueOfEquityShareCapital", D(10)),
        ]
        if i == len(ends) - 1:
            facts += [("INSTANT", "Equity", D(2000)), ("INSTANT", "Assets", D(5000))]
        _filing(
            conn,
            iid,
            str(i),
            end,
            "CONSOLIDATED",
            datetime(end.year, end.month, 28, tzinfo=UTC) + timedelta(days=45),
            facts,
        )
    r = c.get(f"/api/instruments/{iid}/ratios").json()
    by = {x["key"]: x for x in r["ratios"]}
    assert (r["basis"], r["bank"], r["latest_period"]) == ("CONSOLIDATED", False, "2026-06-30")
    assert by["revenue_growth"]["value"] == "36.3636"  # 1500 against 1100 a year earlier
    assert (
        by["roe"]["value"] is not None
        and by["roe"]["as_of"] == "2026-06-30"
        and by["roe"]["unit"] == "pct"
    )
    assert by["pe"]["value"] is not None and r["price"]["value"] == "2.0000"
    assert (
        by["market_cap"]["year_ago"] is not None
    )  # valued at last year's results with that day's close
    assert by["market_cap"]["history"][-1]["period_end"] == "2026-06-30"
    assert by["roe"]["reading"] in {"good", "ok", "weak"} and "owners" in by["roe"]["meaning"]
    assert (
        by["revenue_growth"]["history"]
        and by["revenue_growth"]["history"][-1]["period_end"] == "2026-06-30"
    )
    assert [x["key"] for x in r["ratios"] if x["group"] == "valuation"][0] == "market_cap"
    conn.execute(  # a later close, so the split below went ex between the results and the price
        "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,dataset_version,ingested_at)"
        " VALUES (%s,'2026-09-10 03:45+00',1,2,1,1,100,'nse',1,%s)",
        (iid, NOW),
    )
    conn.execute(
        "INSERT INTO corporate_action (instrument_id,ex_date,kind,status,num,den,subject,knowledge_time,"
        "knowledge_time_source,source,raw_checksum,ingested_at) VALUES (%s,'2026-09-01','split','ok',2,1,'t',%s,'ex_date_proxy','nse','x',%s)",
        (iid, NOW, NOW),
    )
    after = {x["key"]: x for x in c.get(f"/api/instruments/{iid}/ratios").json()["ratios"]}
    assert after["pe"]["value"] is None and "split or bonus" in after["pe"]["note"]


def test_the_corporate_action_review_worklist_is_served_ranked(api, conn):
    client, iid, _ = api
    conn.execute("INSERT INTO instrument_alias (instrument_id, source, source_symbol, valid_from)"
                 " VALUES (%s,'nse','XYZ','2000-01-01')", (iid,))  # fmt: skip
    for kind in ("dividend", "demerger"):
        conn.execute(
            "INSERT INTO corporate_action (instrument_id,ex_date,kind,status,reason,subject,"
            "knowledge_time,knowledge_time_source,source,raw_checksum,ingested_at) VALUES"
            " (%s,'2025-06-10',%s,'review','r','s',%s,'ex_date_proxy','nse','x',%s)",
            (iid, kind, NOW, NOW),
        )
    body = client.get("/api/corporate-actions/review?limit=1").json()
    assert (body["total"], body["by_kind"]) == (2, {"demerger": 1, "dividend": 1})
    assert [r["kind"] for r in body["items"]] == ["demerger"]
