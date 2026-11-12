from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from algo.backtest.costs import schedule_store
from algo.core.clock import SimClock
from algo.data import freeze
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from tests.support.portal import add_user, make_app, settings, sign_in
from tests.unit.research.test_study import spec

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)


@pytest.fixture
def env(conn, pg_url, tmp_path):
    migrate(conn)
    clock = SimClock(NOW)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    iid = repo.add_instrument(x, "AAA")
    conn.execute(
        "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,adjusted_through,dataset_version,ingested_at)"
        " VALUES (%s,'2026-11-11 03:45+00',1,1,1,1,1,'kite','2026-11-11',1,%s)",
        (iid, NOW),
    )
    freeze.take(conn, "kite", date(2026, 11, 11), NOW, "reference history")
    schedule_store.import_files(conn, Path("config/cost_schedules"), now=NOW)
    add_user(conn, clock, "TRADER", "jane@example.com")
    add_user(conn, clock, "VIEWER", "viewer@example.com")
    return conn, make_app(pg_url, tmp_path, portal=settings(clock))


def body(**over):
    return spec(**over).model_dump(mode="json")


def audit_actions(conn):
    return [
        r[0]
        for r in conn.execute(
            "SELECT action FROM portal_audit WHERE action LIKE 'study.%' ORDER BY audit_id"
        )
    ]


def test_anyone_with_research_access_can_read_studies_but_only_traders_register_them(env):
    conn, app = env
    viewer = sign_in(app, "viewer@example.com")
    assert viewer.get("/api/studies").status_code == 200
    assert viewer.get("/api/studies/options").status_code == 200
    assert viewer.post("/api/studies", json=body()).status_code == 403
    assert TestClient(app).get("/api/studies").status_code == 401


def test_the_options_come_from_the_strategy_its_parameters_and_the_data_we_hold(env):
    conn, app = env
    o = sign_in(app, "viewer@example.com").get("/api/studies/options").json()
    (pullback,) = o["strategies"]
    assert pullback["id"] == "trend_pullback"
    assert {p["name"]: (p["choices"], p["default"]) for p in pullback["params"]}["entry_rsi"] == (
        [20, 25, 30],
        25,
    )
    assert o["segments"] == ["large", "mid", "small", "micro"] and o["timeframes"] == ["1D"]
    assert o["brokers"] == [{"broker": "zerodha", "product": "DELIVERY"}]
    assert o["frozen_through"] == "2026-11-11" and o["survivorship_safe_from"] == "2019-10-01"
    assert o["segment_lists_from"] == "2018-08-01" and o["max_trials"] == 64
    assert o["thresholds"]["owner_max_drawdown"] == "0.25" and len(o["thresholds"]) == 12


def test_a_trader_registers_a_study_which_is_listed_shown_and_audited(env):
    conn, app = env
    c = sign_in(app, "jane@example.com")
    r = c.post("/api/studies", json=body())
    assert r.status_code == 200, r.text
    sid = r.json()["experiment_id"]
    listed = c.get("/api/studies").json()["studies"]
    assert [(s["experiment_id"], s["trials_planned"], s["trials_run"]) for s in listed] == [
        (sid, 12, 0)
    ]
    d = c.get(f"/api/studies/{sid}").json()
    assert d["spec"]["holdout_start"] == "2024-05-01" and d["registered_at"].startswith(
        "2026-11-12T06:00"
    )
    assert d["data_freeze"]["through"] == "2026-11-11" and len(d["combinations"]) == 12
    assert c.get("/api/studies/9999").status_code == 404
    assert audit_actions(conn) == ["study.registered"]


def test_a_study_that_cannot_be_honoured_is_refused_with_the_reason_and_nothing_is_registered(env):
    conn, app = env
    c = sign_in(app, "jane@example.com")
    r = c.post("/api/studies", json=body(start="2016-01-01"))
    assert r.status_code == 400 and "survivorship" in r.json()["detail"]
    assert c.post("/api/studies", json={**body(), "colour": "blue"}).status_code == 422
    assert c.get("/api/studies").json()["studies"] == [] and audit_actions(conn) == []
