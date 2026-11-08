import json
from datetime import UTC, date, datetime
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from algo.api.app import create_app
from algo.data.benchmark import ingest, register, store_validation
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate

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
                    "applies_to": ["ALL"],
                    "blocks": ["INTRADAY_RESEARCH"],
                }
            ]
        },
    )
    write(a / "benchmark_alignment_report.json", {"benchmarks": {}})
    write(a / "session_reconciliation_report.json", {
        "calendar_version": {"sessions_file_sha256": "abc"}, "evidence": {"bhavcopy_range": ["a", "b"]},
        "observed_counts": {"CONFIRMED_REGULAR": 2},
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
    return TestClient(create_app(pg_url, docs)), iid, bid


def test_health_reports_the_database_and_what_is_not_configured(api):
    r = api[0].get("/api/health").json()
    assert r == {"api": "ok", "database": "ok", "redis": "not configured"}


def test_health_says_so_when_the_database_is_unreachable(docs):
    bad = TestClient(create_app("postgresql://nobody@127.0.0.1:1/none", docs))
    assert bad.get("/api/health").json()["database"].startswith("error")


def test_the_dashboard_keeps_ingested_validated_and_eligible_apart(api):
    d = api[0].get("/api/dashboard").json()
    s = d["benchmarks"]["series"][0]
    assert d["benchmarks"]["release"] == "1.1" and d["benchmarks"]["gate"] == "disabled"
    assert (s["ingested"], s["technically_validated"], s["research_eligible_daily"],
            s["research_eligible_intraday"], s["benchmark_gate_eligible"]) == (True, True, True, False, False)  # fmt: skip
    assert s["eligibility_state"] == "RESEARCH_ELIGIBLE"
    assert d["platform"]["state"] == "UNKNOWN" and d["strategies"]["persisted"] is False
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
    c = TestClient(create_app(pg_url, tmp_path))
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
    assert [f["id"] for f in d["findings"]] == ["U02"] and d["instrument_level_blocked_dates"] == []
    assert d["session_calendar"]["historical_session_hours"] == "hours are assumed"
    assert d["session_calendar"]["outcome_counts_all_series"] == {"CONFIRMED_REGULAR": 2}
    assert c.get("/api/benchmarks/99").status_code == 404
    lv = c.get(f"/api/benchmarks/{bid}/levels").json()["levels"]
    assert [p["date"] for p in lv] == ["2024-01-01", "2024-01-02", "2024-01-03"]
    assert c.get(f"/api/benchmarks/{bid}/levels", params={"max_points": 2}).status_code == 422
    assert c.get("/api/benchmarks/99/levels").status_code == 404


def test_backtests_and_system_activity(api):
    c, _, bid = api
    assert c.get("/api/backtests").json() == []
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
    a = TestClient(create_app(pg_url, docs)).get("/api/system/activity").json()
    assert a["validations"] == [{"benchmark_id": 1, "latest": None}]


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
    run = c.get("/api/backtests").json()[0]
    assert run["strategy_id"] == "s" and run["ledger_reconciled"] is True
    full = c.get(f"/api/backtests/{run['run_id']}").json()
    assert full["result_hash"] == "rh" and full["reader_mode"] == "research"
