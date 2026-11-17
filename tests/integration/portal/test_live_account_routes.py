# ruff: noqa: E501
"""One person, a paper account and a live account side by side: every account route takes `mode` (paper by default, so nothing existing changes), a live
account runs only a strategy promoted to the LIVE stage, and `live-status` says whether live can run and why not."""

from datetime import timedelta

import pytest

from algo.live import heartbeat
from algo.paper import book
from tests.integration.portal.test_paper_routes import (  # noqa: F401  (env is a fixture)
    CREATE,
    START,
    accounts,
    audit_actions,
    env,
    order,
    owner,
    trader,
)

pytestmark = pytest.mark.integration
STRATEGY = {
    "name": "Cautious",
    "universe": "nifty100",
    "max_instruments": 50,
    "timeframe": "1D",
    "params": {"entry_rsi": 30},
}


def go_live(conn, uid, config_id):
    conn.execute(
        "INSERT INTO strategy_stage_change (config_id, from_stage, to_stage, approver_user_id, at, reason) VALUES (%s,'RESEARCH','LIVE',%s,%s,'drill')",
        (config_id, uid, START),
    )


def test_a_person_starts_a_paper_and_a_live_account_side_by_side(env):  # noqa: F811
    conn, app, clock, _ = env
    uid, c = trader(conn, app, clock)
    assert c.get("/api/paper/account?mode=live").json()["account"] is None
    assert c.post("/api/paper/account", json={**CREATE, "mode": "live"}).json() == {"ok": True}
    live = c.get("/api/paper/account?mode=live").json()["account"]
    assert live["mode"] == "LIVE" and live["initial_cash"] == "100000"
    assert (
        c.get("/api/paper/account").json()["account"] is None
    )  # the default is still paper, and there is none yet
    assert c.post("/api/paper/account", json=CREATE).json() == {"ok": True}
    assert c.get("/api/paper/account").json()["account"]["mode"] == "PAPER"
    again = c.post("/api/paper/account", json={**CREATE, "mode": "live"})
    assert again.status_code == 400 and "already has a live account" in again.json()["detail"]
    assert audit_actions(conn, "paper.account_created") == ["paper.account_created"] * 2
    assert book.get_account(conn, book.account_key(uid, "LIVE"))["owner_user_id"] == uid


def test_orders_are_listed_and_answered_on_the_chosen_account_only(env):  # noqa: F811
    conn, app, clock, ids = env
    uid, c = trader(conn, app, clock)
    accounts(conn, uid)  # paper
    c.post("/api/paper/account", json={**CREATE, "mode": "live"})
    live = book.account_key(uid, "LIVE")
    mine = order(conn, live, ids["AAA"])
    assert c.get("/api/paper/orders").json()["orders"] == []  # not on the paper account
    assert [o["order_id"] for o in c.get("/api/paper/orders?mode=live").json()["orders"]] == [
        str(mine)
    ]
    assert c.post(f"/api/paper/orders/{mine}/approve").status_code == 404  # paper does not know it
    assert c.post(f"/api/paper/orders/{mine}/approve?mode=live").json() == {"ok": True}
    row = conn.execute(
        "SELECT status, decided_by FROM paper_order WHERE order_id=%s", (mine,)
    ).fetchone()
    assert row == ("APPROVED", uid)  # queued for the live process, and the person is on record
    assert conn.execute("SELECT count(*) FROM oms_event").fetchone()[0] == 0  # the API sent nothing


def test_a_live_account_runs_only_a_strategy_in_the_live_stage(env):  # noqa: F811
    conn, app, clock, _ = env
    uid, c = trader(conn, app, clock)
    accounts(conn, uid)
    c.post("/api/paper/account", json={**CREATE, "mode": "live"})
    cid = c.post("/api/strategies", json=STRATEGY).json()["config_id"]
    refused = c.post(f"/api/strategies/{cid}/use?mode=live", json={})
    assert refused.status_code == 400 and "LIVE stage" in refused.json()["detail"]
    assert c.post(f"/api/strategies/{cid}/use", json={}).json() == {
        "ok": True
    }  # paper takes any strategy
    go_live(conn, uid, cid)
    assert c.post(f"/api/strategies/{cid}/use?mode=live", json={}).json() == {"ok": True}
    assert str(book.get_account(conn, book.account_key(uid, "LIVE"))["config_id"]) == cid


def test_a_research_definition_cannot_start_on_a_live_account(env):  # noqa: F811
    conn, app, clock, _ = env
    _, c = owner(conn, app, clock)
    c.post("/api/paper/account", json={**CREATE, "mode": "live"})
    r = c.post("/api/paper/definitions/1/start?mode=live")
    assert r.status_code == 400 and "LIVE stage" in r.json()["detail"]


def test_live_status_says_why_live_cannot_run_and_whether_the_process_is_alive(env, monkeypatch):  # noqa: F811
    conn, app, clock, _ = env
    monkeypatch.delenv("ALGO_LIVE", raising=False)
    _, c = trader(conn, app, clock)
    assert c.get("/api/paper/live-status").json()["account"] is False
    c.post("/api/paper/account", json={**CREATE, "mode": "live"})
    s = c.get("/api/paper/live-status").json()
    assert s["account"] is True and s["open"] is False and s["process"] is None
    text = " | ".join(s["problems"])
    assert "ALGO_LIVE=1 is not set" in text and "no valid broker session" in text
    assert "not the LIVE stage" in text and "no strategy yet" in text
    heartbeat.beat(
        conn, "live", "RUNNING", "", clock.now() - timedelta(seconds=30), pid=1, host="h"
    )
    assert c.get("/api/paper/live-status").json()["process"] == {
        "state": "RUNNING",
        "silent_s": 30,
        "detail": "",
    }


def test_risk_limits_are_kept_per_account(env):  # noqa: F811
    conn, app, clock, _ = env
    uid, c = trader(conn, app, clock)
    accounts(conn, uid)
    c.post("/api/paper/account", json={**CREATE, "mode": "live"})
    assert (
        c.put("/api/risk/limits?mode=live", json={"limits": {"max_open_orders": 2}}).status_code
        == 200
    )
    assert c.get("/api/risk?mode=live").json()["limits"].get("max_open_orders") == 2
    assert not c.get("/api/risk?mode=paper").json()["limits"].get("max_open_orders")
