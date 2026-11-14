from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from algo.core.clock import SimClock
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.paper import book
from tests.support.bt import put_bars
from tests.support.portal import add_user, make_app, settings, sign_in

pytestmark = pytest.mark.integration
START = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)
TODAY = date(2026, 11, 11)
CREATE = {
    "initial_cash": "100000",
    "universe": "nifty100",
    "max_instruments": 50,
    "timeframe": "1D",
    "params": {"entry_rsi": 30},
}


@pytest.fixture
def env(conn, pg_url, tmp_path):
    migrate(conn)
    clock = SimClock(START)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    ids = {s: repo.add_instrument(x, s) for s in ("AAA", "BBB")}
    for i in ids.values():
        repo.add_terms(i, date(2000, 1, 1), None, D(1), D("0.05"), D(1))
    put_bars(conn, ids["AAA"], {TODAY - timedelta(days=1): D("200"), TODAY: D("210")})
    return conn, make_app(pg_url, tmp_path, portal=settings(clock)), clock, ids


def trader(conn, app, clock, email="jane@example.com"):
    uid = add_user(conn, clock, "TRADER", email)
    return uid, sign_in(app, email)


def order(conn, uid, iid, status="PENDING", side="BUY", qty=10, expires_in=timedelta(hours=20)):
    return conn.execute(
        "INSERT INTO paper_order (user_id, decision_day, instrument_id, side, qty, ref_price, reason, status, created_at, not_before, expires_at)"
        " VALUES (%s,%s,%s,%s,%s,200,'entry: oversold in an uptrend',%s,%s,%s,%s) RETURNING order_id",
        (uid, TODAY, iid, side, qty, status, START, START, START + expires_in),
    ).fetchone()[0]


def accounts(conn, *users):
    for u in users:
        book.create_account(
            conn,
            u,
            strategy_id="trend_pullback",
            params={},
            initial_cash=D(100000),
            started_on=TODAY,
            now=START,
        )


def audit_actions(conn, like):
    rows = conn.execute(
        "SELECT action FROM portal_audit WHERE action LIKE %s ORDER BY audit_id", (like,)
    )
    return [r[0] for r in rows]


def test_only_people_who_may_trade_can_use_the_paper_routes(env):
    conn, app, clock, _ = env
    add_user(conn, clock, "VIEWER", "viewer@example.com")
    add_user(conn, clock, "TRADER", "jane@example.com")
    viewer = sign_in(app, "viewer@example.com")
    routes = [
        ("GET", "/api/paper/account"),
        ("POST", "/api/paper/account"),
        ("POST", "/api/paper/account/settings"),
        ("GET", "/api/paper/summary"),
        ("GET", "/api/paper/orders"),
        ("POST", "/api/paper/orders/x/approve"),
        ("POST", "/api/paper/orders/x/reject"),
        ("GET", "/api/paper/runs"),
    ]
    for method, path in routes:
        body = {} if method == "POST" else None
        assert viewer.request(method, path, json=body).status_code == 403, path
        assert TestClient(app).request(method, path, json=body).status_code == 401, path
    assert sign_in(app, "jane@example.com").get("/api/paper/account").status_code == 200


def test_no_account_yet_shows_the_choices_that_exist(env):
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    d = c.get("/api/paper/account").json()
    assert d["label"] == "UNVALIDATED" and d["account"] is None
    assert [u["key"] for u in d["options"]["universes"]] == [
        "nifty50",
        "nifty100",
        "nifty200",
        "midcap100",
        "nifty500",
    ]
    assert [(t["key"], t["available"]) for t in d["options"]["timeframes"]] == [
        ("1D", True),
        ("1h", False),
        ("15m", False),
    ]
    grid = {
        "trend_sma": [100, 200],
        "entry_rsi": [20, 25, 30],
        "exit_rsi": [55, 60, 65],
        "max_positions": [5, 10, 20],
    }
    assert d["options"]["params"] == grid


def test_an_account_is_started_with_the_chosen_settings_once_and_audited(env):
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    assert c.post("/api/paper/account", json=CREATE).json() == {"ok": True}
    a = c.get("/api/paper/account").json()["account"]
    assert a == {
        "strategy_id": "trend_pullback", "enabled": True, "mode": "PAPER", "initial_cash": "100000",
        "started_on": "2026-11-11", "attention": None, "universe": "nifty100", "max_instruments": 50,
        "timeframe": "1D", "params": {"trend_sma": 200, "entry_rsi": 30, "exit_rsi": 60, "max_positions": 10},
        "screen": None,
    }  # fmt: skip
    assert c.post("/api/paper/account", json=CREATE).status_code == 400  # already has one
    other, c2 = trader(conn, app, clock, "bob@example.com")
    bad = {
        "universe": {**CREATE, "universe": "nifty9000"},
        "timeframe": {**CREATE, "timeframe": "15m"},
        "params": {**CREATE, "params": {"entry_rsi": 99}},
        "unknown param": {**CREATE, "params": {"nope": 1}},
    }
    for why, body in bad.items():
        assert c2.post("/api/paper/account", json=body).status_code == 400, why
    assert c2.post("/api/paper/account", json={**CREATE, "initial_cash": "0"}).status_code == 422
    assert c2.post("/api/paper/account", json={**CREATE, "max_instruments": 3}).status_code == 422
    assert book.get_account(conn, other) is None  # nothing half-created
    assert audit_actions(conn, "paper.%") == ["paper.account_created"]


def test_the_settings_can_be_changed_cleared_and_switched_off(env):
    conn, app, clock, _ = env
    uid, c = trader(conn, app, clock)
    assert (
        c.post("/api/paper/account/settings", json={"universe": "nifty50"}).status_code == 404
    )  # nothing to change yet
    c.post("/api/paper/account", json=CREATE)
    body = {"universe": "nifty500", "max_instruments": 100, "params": {"max_positions": 5}}
    assert c.post("/api/paper/account/settings", json=body).json() == {"ok": True}
    a = book.get_account(conn, uid)
    assert (a["universe"], a["max_instruments"]) == ("nifty500", 100)
    assert (a["params"]["max_positions"], a["params"]["entry_rsi"]) == (5, 30)
    assert c.post("/api/paper/account/settings", json={"max_instruments": None}).json() == {
        "ok": True
    }
    assert (
        book.get_account(conn, uid)["max_instruments"] is None
    )  # an explicit null means the whole index
    assert c.post("/api/paper/account/settings", json={"universe": "nifty200"}).json() == {
        "ok": True
    }
    assert book.get_account(conn, uid)["max_instruments"] is None  # leaving it out changes nothing
    assert c.post("/api/paper/account/settings", json={"enabled": False}).json() == {"ok": True}
    assert book.get_account(conn, uid)["enabled"] is False
    for bad in ({"universe": "x"}, {"timeframe": "1h"}, {"params": {"exit_rsi": 1}}):
        assert c.post("/api/paper/account/settings", json=bad).status_code == 400
    assert audit_actions(conn, "paper.settings_changed") == ["paper.settings_changed"] * 4


def test_the_summary_values_the_account_at_the_latest_prices_and_hides_other_peoples_accounts(env):
    conn, app, clock, ids = env
    uid, c = trader(conn, app, clock)
    other, c2 = trader(conn, app, clock, "bob@example.com")
    accounts(conn, uid, other)
    book.record_fill(
        conn,
        uid,
        day=TODAY,
        side="BUY",
        iid=ids["AAA"],
        qty=D(100),
        price=D("200"),
        commission=D("5"),
        charges=[("STT", D("2.5"))],
        ref="r1",
        now=START,
    )
    book.record_fill(
        conn,
        other,
        day=TODAY,
        side="BUY",
        iid=ids["AAA"],
        qty=D(1),
        price=D("200"),
        commission=D(0),
        charges=[],
        ref="r2",
        now=START,
    )
    conn.execute(
        "INSERT INTO paper_equity (user_id, day, equity, cash) VALUES (%s,%s,100000,100000),(%s,%s,100992.5,79992.5)",
        (uid, TODAY - timedelta(days=1), uid, TODAY),
    )
    order(conn, uid, ids["BBB"])
    order(conn, uid, ids["BBB"], status="REJECTED")
    s = c.get("/api/paper/summary").json()
    assert (s["cash"], s["invested"], s["equity"]) == ("79992.5", "21000", "100992.5")
    assert s["pnl"] == {"realized": "0", "unrealized": "1000", "fees": "7.5", "net": "992.5"}
    assert s["positions"] == [
        {"instrument_id": ids["AAA"], "symbol": "AAA", "qty": "100", "avg_cost": "200", "last_price": "210", "value": "21000", "unrealized": "1000", "upcoming": []}
    ]  # fmt: skip
    assert [p["day"] for p in s["equity_curve"]] == ["2026-11-10", "2026-11-11"] and s[
        "pending_orders"
    ] == 1
    assert c2.get("/api/paper/summary").json()["positions"][0]["qty"] == "1"


def test_a_holding_or_an_open_order_with_an_action_coming_within_ten_days_carries_a_warning(env):
    conn, app, clock, ids = env
    uid, c = trader(conn, app, clock)
    accounts(conn, uid)
    book.record_fill(conn, uid, day=TODAY, side="BUY", iid=ids["AAA"], qty=D(100), price=D("200"),
                     commission=D(0), charges=[], ref="r1", now=START)  # fmt: skip
    waiting = order(conn, uid, ids["BBB"])
    answered = order(conn, uid, ids["BBB"], status="REJECTED")
    for iid, ex, kind, amount, subject in (
        (
            ids["AAA"],
            "2026-11-20",
            "dividend",
            7,
            "Interim Dividend - Rs 7 Per Share",
        ),  # 9 days away
        (ids["AAA"], "2026-12-30", "bonus", None, "Bonus 1:1"),  # far away: not a warning yet
        (ids["BBB"], "2026-11-15", "split", None, "Face Value Split"),  # 4 days away
        (
            ids["BBB"],
            "2026-11-10",
            "dividend",
            3,
            "Interim Dividend - Rs 3 Per Share",
        ),  # already passed
    ):
        conn.execute(
            "INSERT INTO corporate_action_upcoming (instrument_id, ex_date, kind, status, amount, subject, fetched_at)"
            " VALUES (%s,%s,%s,'ok',%s,%s,%s)", (iid, ex, kind, amount, subject, START))  # fmt: skip
    held = c.get("/api/paper/summary").json()["positions"][0]["upcoming"]
    assert [(u["ex_date"], u["kind"], u["amount"]) for u in held] == [
        ("2026-11-20", "dividend", "7")
    ]
    assert held[0]["subject"] == "Interim Dividend - Rs 7 Per Share"
    rows = {r["order_id"]: r for r in c.get("/api/paper/orders").json()["orders"]}
    assert [(u["ex_date"], u["kind"]) for u in rows[str(waiting)]["upcoming"]] == [
        ("2026-11-15", "split")
    ]
    assert rows[str(answered)]["upcoming"] == []  # a decided order has nothing left to warn about


def test_a_holding_with_no_price_is_valued_at_what_it_cost(env):
    conn, app, clock, ids = env
    uid, c = trader(conn, app, clock)
    accounts(conn, uid)
    book.record_fill(
        conn,
        uid,
        day=TODAY,
        side="BUY",
        iid=ids["BBB"],
        qty=D(10),
        price=D(50),
        commission=D(0),
        charges=[],
        ref="r",
        now=START,
    )
    p = c.get("/api/paper/summary").json()["positions"][0]
    assert (p["last_price"], p["value"], p["unrealized"]) == ("50", "500", "0")


def test_an_account_with_nothing_yet_summarises_as_all_cash(env):
    conn, app, clock, _ = env
    uid, c = trader(conn, app, clock)
    accounts(conn, uid)
    s = c.get("/api/paper/summary").json()
    assert (s["equity"], s["cash"], s["invested"], s["positions"], s["equity_curve"]) == (
        "100000",
        "100000",
        "0",
        [],
        [],
    )
    _, nobody = trader(conn, app, clock, "none@example.com")
    assert nobody.get("/api/paper/summary").status_code == 404  # no account to summarise


def test_orders_are_listed_filtered_and_answered_by_their_owner_only(env):
    conn, app, clock, ids = env
    uid, c = trader(conn, app, clock)
    other, c2 = trader(conn, app, clock, "bob@example.com")
    accounts(conn, uid, other)
    keep, drop = order(conn, uid, ids["AAA"]), order(conn, uid, ids["BBB"], side="SELL")
    stale = order(conn, uid, ids["BBB"], expires_in=-timedelta(hours=1))
    theirs = order(conn, other, ids["AAA"])
    rows = c.get("/api/paper/orders").json()["orders"]
    assert {r["order_id"] for r in rows} == {str(keep), str(drop), str(stale)}
    first = next(r for r in rows if r["order_id"] == str(keep))
    assert first == {
        "order_id": str(keep), "symbol": "AAA", "side": "BUY", "qty": "10", "ref_price": "200",
        "reason": "entry: oversold in an uptrend", "status": "PENDING", "decision_day": "2026-11-11",
        "created_at": START.isoformat(), "expires_at": (START + timedelta(hours=20)).isoformat(),
        "fill_price": None, "fill_commission": None, "fill_day": None, "failure": None, "order_type": "MARKET", "limit_price": None, "tick_size": "0.05",
        "upcoming": [],
    }  # fmt: skip
    assert c.get("/api/paper/orders?status=FILLED,REJECTED").json()["orders"] == []
    assert (
        c.get("/api/paper/orders?status=bogus").json()["orders"] == []
    )  # an unknown status matches nothing, not everything
    assert c.post(f"/api/paper/orders/{keep}/approve").json() == {"ok": True}
    assert c.post(f"/api/paper/orders/{drop}/reject").json() == {"ok": True}
    approved = c.get("/api/paper/orders?status=APPROVED").json()["orders"]
    assert {r["order_id"] for r in approved} == {str(keep)}
    assert c.post(f"/api/paper/orders/{keep}/approve").status_code == 400  # already answered
    assert c.post(f"/api/paper/orders/{stale}/approve").status_code == 400  # past its time
    assert (
        c.post(f"/api/paper/orders/{theirs}/approve").status_code == 404
    )  # someone else's looks like it does not exist
    assert c.post("/api/paper/orders/not-a-uuid/approve").status_code == 404
    assert c2.get("/api/paper/orders").json()["orders"][0]["status"] == "PENDING"
    assert audit_actions(conn, "paper.order%") == ["paper.order_approved", "paper.order_rejected"]


def test_the_decision_log_lists_recent_runs_with_the_reason_and_how_many_orders(env):
    conn, app, clock, ids = env
    uid, c = trader(conn, app, clock)
    accounts(conn, uid)
    order(conn, uid, ids["AAA"])
    order(conn, uid, ids["BBB"])
    runs = (
        (TODAY, "PROPOSED", {"label": "UNVALIDATED", "universe": {"universe": "nifty200"}}),
        (TODAY - timedelta(days=1), "ERROR", {"reason": "no nifty200_list in the lake"}),
    )
    for day, status, detail in runs:
        conn.execute(
            "INSERT INTO paper_run (user_id, decision_day, strategy_id, strategy_version, params_hash, status, detail, created_at) VALUES (%s,%s,'trend_pullback','1','h',%s,%s,%s)",
            (uid, day, status, Jsonb(detail), START),
        )
    assert c.get("/api/paper/runs").json()["runs"] == [
        {"decision_day": "2026-11-11", "status": "PROPOSED", "reason": None, "orders": 2, "universe": "nifty200", "strategy_version": "1", "created_at": START.isoformat()},
        {"decision_day": "2026-11-10", "status": "ERROR", "reason": "no nifty200_list in the lake", "orders": 0, "universe": None, "strategy_version": "1", "created_at": START.isoformat()},
    ]  # fmt: skip


def test_approving_with_a_limit_price_stores_it_and_a_bad_limit_is_a_400(env):
    conn, app, clock, ids = env
    uid, c = trader(conn, app, clock)
    accounts(conn, uid)
    bad, good = order(conn, uid, ids["AAA"]), order(conn, uid, ids["BBB"])  # ref 200
    for body, text in [
        ({"order_type": "LIMIT"}, "needs a limit price"),
        ({"order_type": "LIMIT", "limit_price": "100"}, "more than 20%"),
        ({"order_type": "MARKET", "limit_price": "200"}, "no limit price"),
    ]:
        r = c.post(f"/api/paper/orders/{bad}/approve", json=body)
        assert r.status_code == 400 and text in r.json()["detail"]
    assert (
        c.post(f"/api/paper/orders/{bad}/approve", json={"order_type": "STOP"}).status_code == 422
    )
    assert (
        c.post(
            f"/api/paper/orders/{good}/approve",
            json={"order_type": "LIMIT", "limit_price": "199.5"},
        ).status_code
        == 200
    )
    got = {r["order_id"]: r for r in c.get("/api/paper/orders").json()["orders"]}
    assert (got[str(good)]["order_type"], got[str(good)]["limit_price"]) == ("LIMIT", "199.5")
    assert c.post(f"/api/paper/orders/{bad}/approve").status_code == 200  # no body: a market order
