"""A screener saved as a strategy, and one stock's buy/sell decisions under it. ENGINEERING_TEST_ONLY: synthetic prices."""

import pytest

from algo.data.store.instruments import InstrumentRepo
from tests.integration.portal.test_paper_routes import (  # noqa: F401  (env is a fixture)
    accounts,
    audit_actions,
    env,
    trader,
)
from tests.support.market import put, put_path, sessions

pytestmark = pytest.mark.integration
NAMES = ("FAST", "TURN", "FALLING")
SCREEN = {
    "conditions": [{"field": "chg_1m", "op": "gt", "value": 0}],
    "match": "all",
    "sort": "chg_1m",
    "descending": True,
}
BODY = {
    "name": "Rising",
    "universe": "segments",
    "max_instruments": None,
    "timeframe": "1D",
    "params": {"max_positions": 5},
    "screen": {**SCREEN, "segments": ["large", "mid"]},
}


@pytest.fixture
def market(env, monkeypatch):  # noqa: F811
    monkeypatch.setenv("ALGO_PRICE_SOURCE", "kite")
    conn, app, clock, _ = env
    x = conn.execute("SELECT exchange_id FROM exchange LIMIT 1").fetchone()[0]
    repo = InstrumentRepo(conn)
    ids = {s: repo.add_instrument(x, s, isin=f"INE10000000{i}") for i, s in enumerate(NAMES, 1)}
    days = sessions(520)
    put(conn, ids["FAST"], "0.004", days)
    put(conn, ids["FALLING"], "-0.002", days)
    put_path(conn, ids["TURN"], days, [(260, "-0.002"), (1, "0.004")])  # falls, then rises
    return conn, app, clock, ids


def test_a_screener_is_saved_listed_and_changed_like_any_strategy(market):
    conn, app, clock, _ = market
    _, c = trader(conn, app, clock)
    cid = c.post("/api/strategies", json=BODY).json()["config_id"]
    got = c.get("/api/strategies").json()["strategies"][0]
    assert got["strategy_id"] == "screener" and got["universe"] == "segments"
    assert got["params"] == {"max_positions": 5}
    assert (
        got["screen"]["segments"] == ["large", "mid"]
        and got["screen"]["screen"]["sort"] == "chg_1m"
    )
    assert audit_actions(conn, "strategy.%") == ["strategy.created"]
    bolder = {**BODY, "name": "Bolder", "params": {"max_positions": 10}}
    assert c.post(f"/api/strategies/{cid}", json=bolder).json() == {"ok": True}
    got = c.get("/api/strategies").json()["strategies"][0]
    assert got["name"] == "Bolder" and got["params"] == {"max_positions": 10}


def test_a_screener_that_cannot_be_backtested_or_has_bad_settings_is_refused(market):
    conn, app, clock, _ = market
    _, c = trader(conn, app, clock)
    seg = {**BODY["screen"], "conditions": [{"field": "segment", "op": "eq", "value": "large"}]}
    r = c.post("/api/strategies", json={**BODY, "screen": seg})
    assert r.status_code == 400 and "segment" in r.json()["detail"]
    slots = {**BODY, "params": {"max_positions": 7}}
    assert c.post("/api/strategies", json=slots).status_code == 400
    none = {**BODY, "screen": {**BODY["screen"], "segments": []}}  # refused by the body check (422)
    assert c.post("/api/strategies", json=none).status_code == 422
    assert c.get("/api/strategies").json()["strategies"] == []
    # a trend strategy cannot become a screener, nor the reverse
    cid = c.post("/api/strategies", json=BODY).json()["config_id"]
    trend = {
        "name": "T",
        "universe": "nifty100",
        "max_instruments": None,
        "timeframe": "1D",
        "params": {},
    }
    assert c.post(f"/api/strategies/{cid}", json=trend).status_code == 400
    tid = c.post("/api/strategies", json=trend).json()["config_id"]
    assert c.post(f"/api/strategies/{tid}", json=BODY).status_code == 400


def test_a_screener_strategy_can_be_given_to_the_paper_account_which_then_refuses_hand_edits(
    market,
):
    conn, app, clock, _ = market
    uid, c = trader(conn, app, clock)
    accounts(conn, uid)
    cid = c.post("/api/strategies", json=BODY).json()["config_id"]
    assert c.post(f"/api/strategies/{cid}/use").json() == {"ok": True}
    acct = c.get("/api/paper/account").json()["account"]
    assert acct["strategy_id"] == "screener" and acct["universe"] == "segments"
    assert acct["params"] == {"max_positions": 5} and acct["screen"]["segments"] == ["large", "mid"]
    r = c.post("/api/paper/account/settings", json={"universe": "nifty50"})
    assert r.status_code == 400 and "screener" in r.json()["detail"]
    assert c.post("/api/paper/account/settings", json={"enabled": False}).json() == {"ok": True}


def test_one_stocks_decisions_follow_the_screen_every_day(market):
    conn, app, clock, ids = market
    _, c = trader(conn, app, clock)
    cid = c.post("/api/strategies", json=BODY).json()["config_id"]
    days = sessions(520)
    q = {"start": "2024-01-01", "end": days[-1].isoformat()}

    def marks(name):
        r = c.get(f"/api/strategies/{cid}/signals", params={**q, "instrument_id": ids[name]})
        assert r.status_code == 200, r.text
        return r.json(), [(x["day"], x["action"]) for x in r.json()["days"] if x["action"]]

    fast, fast_marks = marks("FAST")
    assert fast["label"] == "UNVALIDATED" and fast["strategy"] == "Rising"
    assert "pending" not in fast and "stopped matching" in " ".join(fast["notes"])
    assert fast_marks == [
        (days[21].isoformat(), "BUY")
    ]  # a month of closes is needed, then it matches for good
    assert fast["summary"] == {"buys": 1, "sells": 0}
    buy = next(x for x in fast["days"] if x["action"] == "BUY")
    assert buy["fill_day"] == days[22].isoformat() and isinstance(buy["fill_price"], str)
    assert marks("FALLING")[1] == []  # never matches "rising over a month"
    turn = marks("TURN")[1]
    assert (
        len(turn) == 1 and turn[0][1] == "BUY" and turn[0][0] > days[260].isoformat()
    )  # buys once it turns up


def test_a_stock_that_stops_matching_is_marked_sold_the_day_it_stops(market):
    conn, app, clock, ids = market
    _, c = trader(conn, app, clock)
    x = conn.execute("SELECT exchange_id FROM exchange LIMIT 1").fetchone()[0]
    repo = InstrumentRepo(conn)
    iid = repo.add_instrument(x, "ROUND", isin="INE100000099")
    put_path(
        conn, iid, sessions(520), [(120, "0.004"), (1, "-0.004")]
    )  # rises, then falls for good
    cid = c.post("/api/strategies", json=BODY).json()["config_id"]
    d = c.get(
        f"/api/strategies/{cid}/signals",
        params={"instrument_id": iid, "start": "2024-01-01", "end": sessions(520)[-1].isoformat()},
    ).json()
    acts = [(x["action"], x["reason"]) for x in d["days"] if x["action"]]
    assert acts == [("BUY", "matches the screen"), ("SELL", "no longer matches the screen")]
    sell = next(x for x in d["days"] if x["action"] == "SELL")
    assert sell["day"] > sessions(520)[120].isoformat() and sell["holding_after"] is False


def test_the_screener_signals_keep_the_same_refusals_as_the_others(market):
    conn, app, clock, ids = market
    _, c = trader(conn, app, clock)
    _, c2 = trader(conn, app, clock, "bob@example.com")
    cid = c.post("/api/strategies", json=BODY).json()["config_id"]
    ok = {"instrument_id": ids["FAST"], "start": "2025-04-01", "end": "2025-05-01"}
    assert c2.get(f"/api/strategies/{cid}/signals", params=ok).status_code == 404
    assert (
        c.get(f"/api/strategies/{cid}/signals", params={**ok, "instrument_id": 999999}).status_code
        == 404
    )
    assert (
        c.get(f"/api/strategies/{cid}/signals", params={**ok, "end": "2025-01-01"}).status_code
        == 422
    )


def test_a_screener_on_filed_ratios_can_be_saved_and_its_chart_signals_are_read(market):
    conn, app, clock, _ = market
    _, c = trader(conn, app, clock)
    pe = {**BODY["screen"], "conditions": [{"field": "pe", "op": "lt", "value": 15}], "sort": "pe"}
    r = c.post("/api/strategies", json={**BODY, "screen": pe})
    assert r.status_code == 200, r.text
