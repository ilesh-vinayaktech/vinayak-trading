from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from algo.paper import book
from tests.integration.portal.test_paper_routes import (  # noqa: F401  (env is a fixture)
    accounts,
    audit_actions,
    env,
    trader,
)
from tests.support.portal import add_user, sign_in

pytestmark = pytest.mark.integration
BODY = {
    "name": "Cautious",
    "universe": "nifty100",
    "max_instruments": 50,
    "timeframe": "1D",
    "params": {"entry_rsi": 30},
}
FULL = {"trend_sma": 200, "entry_rsi": 30, "exit_rsi": 60, "max_positions": 10}


def test_only_people_who_may_trade_can_use_the_strategy_routes(env):  # noqa: F811
    conn, app, clock, _ = env
    add_user(conn, clock, "VIEWER", "viewer@example.com")
    add_user(conn, clock, "TRADER", "jane@example.com")
    viewer = sign_in(app, "viewer@example.com")
    cid = uuid4()
    routes = [
        ("GET", "/api/strategies"),
        ("GET", f"/api/strategies/{cid}/signals"),
        ("POST", "/api/strategies"),
        ("POST", f"/api/strategies/{cid}"),
        ("POST", f"/api/strategies/{cid}/use"),
        ("POST", f"/api/strategies/{cid}/delete"),
    ]
    for method, path in routes:
        body = {} if method == "POST" else None
        assert viewer.request(method, path, json=body).status_code == 403, path
        assert TestClient(app).request(method, path, json=body).status_code == 401, path


def test_a_strategy_is_created_listed_changed_and_deleted_with_every_step_audited(env):  # noqa: F811
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    first = c.get("/api/strategies").json()
    assert first["strategies"] == [] and first["label"] == "UNVALIDATED"
    assert [u["key"] for u in first["options"]["universes"]][0] == "nifty50"
    cid = c.post("/api/strategies", json=BODY).json()["config_id"]
    listed = c.get("/api/strategies").json()["strategies"]
    assert len(listed) == 1 and listed[0]["config_id"] == cid and listed[0]["in_use"] is False
    assert listed[0]["params"] == FULL
    assert listed[0]["created_at"].startswith("2026-11-11T10:00:00")
    changed = {**BODY, "name": "Bolder", "max_instruments": None, "params": {"entry_rsi": 20}}
    assert c.post(f"/api/strategies/{cid}", json=changed).json() == {"ok": True}
    got = c.get("/api/strategies").json()["strategies"][0]
    assert (got["name"], got["max_instruments"], got["params"]["entry_rsi"]) == ("Bolder", None, 20)
    assert c.post(f"/api/strategies/{cid}/delete", json={}).json() == {"ok": True}
    assert c.get("/api/strategies").json()["strategies"] == []
    assert audit_actions(conn, "strategy.%") == [
        "strategy.created",
        "strategy.changed",
        "strategy.deleted",
    ]


def test_bad_settings_names_and_other_peoples_ids_are_refused_and_change_nothing(env):  # noqa: F811
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    _, c2 = trader(conn, app, clock, "bob@example.com")
    cid = c.post("/api/strategies", json=BODY).json()["config_id"]
    assert c.post("/api/strategies", json=BODY).status_code == 400  # name taken
    for bad in (
        {**BODY, "name": "B1", "universe": "x"},
        {**BODY, "name": "B2", "timeframe": "1h"},
        {**BODY, "name": "B3", "params": {"entry_rsi": 99}},
        {**BODY, "name": "  "},
    ):
        assert c.post("/api/strategies", json=bad).status_code == 400
    assert (
        c.post("/api/strategies", json={**BODY, "name": "B4", "max_instruments": 3}).status_code
        == 422
    )
    assert c2.post(f"/api/strategies/{cid}", json=BODY).status_code == 404
    assert c2.post(f"/api/strategies/{cid}/use", json={}).status_code == 404
    assert c2.post(f"/api/strategies/{cid}/delete", json={}).status_code == 404
    assert len(c.get("/api/strategies").json()["strategies"]) == 1
    assert audit_actions(conn, "strategy.%") == ["strategy.created"]


def test_the_paper_account_picks_a_strategy_and_follows_its_edits(env):  # noqa: F811
    conn, app, clock, _ = env
    uid, c = trader(conn, app, clock)
    cid = c.post("/api/strategies", json=BODY).json()["config_id"]
    assert c.post(f"/api/strategies/{cid}/use", json={}).status_code == 400  # no account yet
    accounts(conn, uid)
    assert c.post(f"/api/strategies/{cid}/use", json={}).json() == {"ok": True}
    a = c.get("/api/paper/account").json()["account"]
    assert (a["universe"], a["max_instruments"], a["params"]["entry_rsi"]) == ("nifty100", 50, 30)
    assert c.get("/api/strategies").json()["strategies"][0]["in_use"] is True
    assert c.post(f"/api/strategies/{cid}/delete", json={}).status_code == 400  # in use
    assert c.post(f"/api/strategies/{cid}", json={**BODY, "universe": "nifty50"}).json() == {
        "ok": True
    }
    assert book.get_account(conn, uid)["universe"] == "nifty50"
    assert audit_actions(conn, "strategy.%") == [
        "strategy.created",
        "strategy.used",
        "strategy.changed",
    ]


def _series(conn, iid):
    """A long rise, a sharp 6-day drop that stays above the 200-day average, then a recovery (about 330 sessions)."""
    from datetime import date, timedelta
    from decimal import Decimal as D

    from tests.support.bt import put_bars

    day, price, out = date(2025, 1, 1), D(100), {}
    steps = [D("1.002")] * 300 + [D("0.97")] * 6 + [D("1.03")] * 12
    for step in steps:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        out[day] = price
        price *= step
        day += timedelta(days=1)
    put_bars(conn, iid, out)
    return sorted(out)


def test_the_signals_replay_one_stocks_decisions_from_a_chosen_day(env):  # noqa: F811
    conn, app, clock, ids = env
    _, c = trader(conn, app, clock)
    cid = c.post("/api/strategies", json=BODY).json()["config_id"]
    days = _series(conn, ids["BBB"])
    q = {"instrument_id": ids["BBB"], "start": days[0].isoformat(), "end": days[-1].isoformat()}
    r = c.get(f"/api/strategies/{cid}/signals", params={**q, "start": days[250].isoformat()})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["strategy"] == "Cautious" and d["label"] == "UNVALIDATED"
    assert d["params"]["entry_rsi"] == 30 and "how many stocks are held" in " ".join(d["notes"])
    assert (
        d["days"][0]["day"] == days[250].isoformat()
        and d["days"][-1]["day"] == days[-1].isoformat()
    )
    actions = [(x["action"], x["reason"]) for x in d["days"] if x["action"]]
    assert actions[0] == ("BUY", "oversold in an uptrend") and d["summary"] == {
        "buys": 1,
        "sells": 1,
    }
    buy = next(x for x in d["days"] if x["action"] == "BUY")
    assert buy["fill_day"] > buy["day"] and isinstance(buy["fill_price"], str)
    assert all(isinstance(x["close"], str) for x in d["days"])
    held = c.get(
        f"/api/strategies/{cid}/signals",
        params={**q, "start": days[250].isoformat(), "holding": "true"},
    ).json()
    assert held["days"][0]["holding_after"] is True or held["days"][0]["action"] == "SELL"


def test_the_signals_refuse_other_peoples_strategies_unknown_stocks_and_bad_ranges(env):  # noqa: F811
    conn, app, clock, ids = env
    _, c = trader(conn, app, clock)
    _, c2 = trader(conn, app, clock, "bob@example.com")
    cid = c.post("/api/strategies", json=BODY).json()["config_id"]
    ok = {"instrument_id": ids["AAA"], "start": "2026-01-01", "end": "2026-02-01"}
    assert (
        c.get(f"/api/strategies/{cid}/signals", params=ok).status_code == 200
    )  # no bars before: nothing ready, still answers
    assert c2.get(f"/api/strategies/{cid}/signals", params=ok).status_code == 404
    assert c.get(f"/api/strategies/{uuid4()}/signals", params=ok).status_code == 404
    assert (
        c.get(f"/api/strategies/{cid}/signals", params={**ok, "instrument_id": 999999}).status_code
        == 404
    )
    assert (
        c.get(f"/api/strategies/{cid}/signals", params={**ok, "end": "2025-01-01"}).status_code
        == 422
    )
    assert (
        c.get(f"/api/strategies/{cid}/signals", params={**ok, "start": "1970-01-01"}).status_code
        == 422
    )
