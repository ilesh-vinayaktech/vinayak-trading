"""The API's real responses, frozen as JSON the frontend parses with its own schemas
(frontend/tests/contract). If an endpoint changes shape, this test fails until the fixtures are
regenerated (UPDATE_CONTRACT=1) - and then the frontend schema test fails until the UI is adapted.
Both sides are therefore tested against what the API actually returns, not hand-written mocks."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from algo.core.clock import SimClock
from algo.data.benchmark import ingest, register, store_validation
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from tests.integration.test_app import NOW, docs, write  # noqa: F401
from tests.support.portal import open_app

pytestmark = pytest.mark.integration
OUT = Path(__file__).parents[2] / "frontend" / "tests" / "contract"


@pytest.fixture
def seeded(conn, pg_url, docs):  # noqa: F811
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    iid = repo.add_instrument(x, "XYZ")
    for i, d in enumerate([(2025, 6, 9), (2025, 6, 10), (2025, 6, 11), (2025, 6, 12)]):
        ts = datetime(*d, 3, 45, tzinfo=UTC)
        conn.execute(
            "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,dataset_version,"
            "ingested_at) VALUES (%s,%s,%s,%s,%s,%s,%s,'nse',1,%s)",
            (iid, ts, 100 + i, 102 + i, 99 + i, 101 + i, 1000 * (i + 1), NOW))  # fmt: skip
    for ex, kind, status in (("2025-06-11", "bonus", "ok"), ("2025-06-12", "demerger", "review")):
        conn.execute(
            "INSERT INTO corporate_action (instrument_id,ex_date,kind,status,num,den,subject,knowledge_time,"
            "knowledge_time_source,source,raw_checksum,ingested_at) VALUES (%s,%s,%s,%s,%s,%s,'t',%s,"
            "'ex_date_proxy','nse','x',%s)", (iid, ex, kind, status, 2 if kind == "bonus" else None,
                                             1 if kind == "bonus" else None, NOW, NOW))  # fmt: skip
    for i in range(6):  # six Kite minutes from 09:15 IST on 2025-06-09
        conn.execute(
            "INSERT INTO bar_1m (instrument_id,ts,open,high,low,close,volume,source,adjusted_through,"
            "dataset_version,ingested_at) VALUES (%s,%s,%s,%s,%s,%s,%s,'kite','2025-06-30',1,%s)",
            (iid, datetime(2025, 6, 9, 3, 45 + i, tzinfo=UTC), 100 + i, 101 + i, 99 + i, 100 + i, 10 * (i + 1), NOW))  # fmt: skip
    bid = register(
        conn,
        name="N200",
        provider="p",
        index_symbol="NIFTY 200",
        return_type="TOTAL_RETURN",
        methodology_version="m",
    )
    from datetime import date
    from decimal import Decimal as D

    ingest(
        conn,
        bid,
        [(date(2024, 1, d), D(100 + d)) for d in (1, 2, 3)],
        source="s",
        source_timestamp=NOW,
        raw_hash="h",
        now=NOW,
    )
    store_validation(conn, bid, report={"report_version": "2", "technical_validation_passed": True, "check_states": {"a": "PASS"},
                                        "owner_accepted_findings": [{"check": "a", "state": "UNRESOLVED", "label": "L", "reason": "r", "detail_sha256": "h"}]},
                     passed=True, normalized_sha256="n", factsheet_sha256=None, unresolved=["x"], now=NOW)  # fmt: skip
    for part, status in (
        ("2025-06-09", "quarantined"),
        ("2025-06-09", "loaded"),
        ("2025-06-10", "loaded"),
    ):
        conn.execute(
            "INSERT INTO partition_load (source,dataset,partition,status,at) VALUES ('nse','bhav',%s,%s,%s)",
            (part, status, NOW),
        )
    conn.execute(
        "INSERT INTO backtest_run (strategy_id,strategy_version,params,params_hash,code_version,reader_mode,config,"
        "cost_model,adjustment_versions,provisional_events,unapplied_events,blocked_instruments,unmodelled_events,"
        "accounting_complete,dividends_received,metrics,result_hash,created_at,ledger_reconciled,reconciliation,pnl)"
        " VALUES ('s','1','{}','ph','c','research','{}','{}','{}','[]','[]','[]','[]',true,0,'{\"sharpe\": 1.2}','rh',%s,true,'{}','{}')", (NOW,))  # fmt: skip
    clock = SimClock(datetime(2026, 11, 8, 4, 51, tzinfo=UTC))
    return TestClient(open_app(pg_url, docs, clock=clock)), iid, bid


def snapshots(c, iid, bid):
    rng = {"start": "2025-06-01", "end": "2025-06-30"}
    return {
        "health": c.get("/api/health"),
        "dashboard": c.get("/api/dashboard"),
        "instrument_search": c.get("/api/instruments", params={"q": "xy"}),
        "instrument_detail": c.get(f"/api/instruments/{iid}"),
        "bars_none": c.get(f"/api/instruments/{iid}/bars", params={**rng, "adjust": "none"}),
        "bars_split": c.get(f"/api/instruments/{iid}/bars", params={**rng, "adjust": "split"}),
        "bars_5m": c.get(f"/api/instruments/{iid}/bars", params={**rng, "timeframe": "5m"}),
        "indicator_catalog": c.get("/api/indicators"),
        "indicator_series": c.get(
            f"/api/instruments/{iid}/indicators",
            params={**rng, "names": "sma:2,macd:2:3:2,supertrend:2:1"},
        ),
        "benchmark_list": c.get("/api/benchmarks"),
        "benchmark_detail": c.get(f"/api/benchmarks/{bid}"),
        "benchmark_levels": c.get(f"/api/benchmarks/{bid}/levels"),
        "backtests": c.get("/api/backtests"),
        "activity": c.get("/api/system/activity"),
    }


def test_the_api_responses_match_the_fixtures_the_frontend_is_tested_against(seeded):
    c, iid, bid = seeded
    for name, resp in snapshots(c, iid, bid).items():
        assert resp.status_code == 200, name
        text = json.dumps(resp.json(), indent=1, sort_keys=True) + "\n"
        path = OUT / f"{name}.json"
        if os.environ.get("UPDATE_CONTRACT") == "1":
            path.write_text(text)
        assert path.read_text() == text, f"{name}: the API response changed; run UPDATE_CONTRACT=1"
