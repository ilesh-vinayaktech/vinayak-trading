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
from tests.support.research_lock import anchor_open_lock
from tests.unit.research.test_study import spec

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)


@pytest.fixture
def env(conn, pg_url, tmp_path):
    migrate(conn)
    anchor_open_lock(conn)
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
    pullback, screener = o["strategies"]
    assert (pullback["id"], screener["id"]) == ("trend_pullback", "screener")
    assert [p["name"] for p in screener["params"]] == ["max_positions"]
    assert {p["name"]: (p["choices"], p["default"]) for p in pullback["params"]}["entry_rsi"] == (
        [20, 25, 30],
        25,
    )
    assert o["segments"] == ["large", "mid", "small", "micro"] and o["timeframes"] == ["1D"]
    assert o["brokers"] == [{"broker": "zerodha", "product": "DELIVERY"}]
    assert o["frozen_through"] == "2026-11-11" and o["survivorship_safe_from"] == "2019-10-01"
    assert o["segment_lists_from"] == "2018-08-01" and o["max_trials"] == 64
    assert o["thresholds"]["owner_max_drawdown"] == "1.0" and len(o["thresholds"]) == 12


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


def test_a_run_is_requested_watched_and_its_trials_read_back_without_the_daily_series(env):
    from algo.research import study_jobs

    conn, app = env
    c = sign_in(app, "jane@example.com")
    sid = c.post("/api/studies", json=body()).json()["experiment_id"]
    empty = c.get(f"/api/studies/{sid}/results").json()
    assert empty == {"run": None, "trials": [], "universe_coverage": []}
    rid = c.post(f"/api/studies/{sid}/runs").json()["run_id"]
    assert c.post(f"/api/studies/{sid}/runs").status_code == 400  # one active run per study
    queued = c.get(f"/api/studies/{sid}/results").json()["run"]
    assert (queued["run_id"], queued["status"], queued["done"], queued["total"]) == (
        rid,
        "QUEUED",
        0,
        0,
    )
    study_jobs.start(
        conn,
        rid,
        12,
        1,
        {
            "universe_coverage": [
                {
                    "list": "2023-12-31",
                    "from": "2024-02-01",
                    "until": "2024-07-31",
                    "in_segments": 250,
                    "matched": 244,
                    "usable": 240,
                }
            ]
        },
        NOW,
    )
    study_jobs.save_trial(
        conn,
        sid,
        {"entry_rsi": 20},
        "h1",
        "DONE",
        NOW,
        metrics={"sharpe": 1.2, "trades": 40},
        returns=[0.01, -0.02],
        seconds=3.5,
    )
    study_jobs.save_trial(
        conn, sid, {"entry_rsi": 25}, "h2", "FAILED", NOW, error="DataNotReady: x"
    )
    r = c.get(f"/api/studies/{sid}/results").json()
    assert r["run"]["status"] == "RUNNING" and (r["run"]["done"], r["run"]["total"]) == (1, 12)
    assert [(t["params"]["entry_rsi"], t["status"]) for t in r["trials"]] == [
        (20, "DONE"),
        (25, "FAILED"),
    ]
    assert (
        r["trials"][0]["metrics"]["sharpe"] == 1.2
        and "returns" not in r["trials"][0]
        and r["trials"][1]["error"] == "DataNotReady: x"
    )
    assert r["universe_coverage"][0]["usable"] == 240
    assert audit_actions_like(conn, "study.run%") == ["study.run_requested"]


def audit_actions_like(conn, like):
    return [
        x[0]
        for x in conn.execute(
            "SELECT action FROM portal_audit WHERE action LIKE %s ORDER BY audit_id", (like,)
        )
    ]


def test_only_the_person_who_may_run_strategies_starts_or_cancels_a_run_and_a_started_run_is_asked_to_stop(
    env,
):
    from algo.research import study_jobs

    conn, app = env
    jane, viewer = sign_in(app, "jane@example.com"), sign_in(app, "viewer@example.com")
    sid = jane.post("/api/studies", json=body()).json()["experiment_id"]
    assert viewer.post(f"/api/studies/{sid}/runs").status_code == 403
    assert viewer.get(f"/api/studies/{sid}/results").status_code == 200
    rid = jane.post(f"/api/studies/{sid}/runs").json()["run_id"]
    assert viewer.post(f"/api/studies/runs/{rid}/cancel").status_code == 403
    assert jane.post(f"/api/studies/runs/{rid}/cancel").json() == {"ok": True}
    assert jane.get(f"/api/studies/{sid}/results").json()["run"]["status"] == "CANCELLED"
    assert jane.post(f"/api/studies/runs/{rid}/cancel").status_code == 400  # already cancelled
    assert jane.post("/api/studies/9999/runs").status_code == 404
    rid2 = jane.post(f"/api/studies/{sid}/runs").json()["run_id"]
    study_jobs.claim(conn, NOW)
    assert jane.post(f"/api/studies/runs/{rid2}/cancel").json() == {
        "ok": True
    }  # it has started: asked to stop
    assert jane.get(f"/api/studies/{sid}/results").json()["run"]["cancel_requested"] is True
    study_jobs.finish(conn, rid2, "CANCELLED", NOW)  # what the worker does at its next check
    assert (
        jane.post(f"/api/studies/runs/{rid2}/cancel").status_code == 400
    )  # finished: nothing to stop
    assert audit_actions_like(conn, "study.run%") == [
        "study.run_requested",
        "study.run_cancelled",
        "study.run_requested",
        "study.run_cancelled",
    ]


def test_a_verdict_needs_every_trial_finished_and_is_a_separate_job_from_the_trials(env):
    from algo.research import study_jobs

    conn, app = env
    jane, viewer = sign_in(app, "jane@example.com"), sign_in(app, "viewer@example.com")
    sid = jane.post("/api/studies", json=body()).json()["experiment_id"]
    planned = jane.get(f"/api/studies/{sid}").json()["trials_planned"]
    nothing = jane.get(f"/api/studies/{sid}/verdict").json()
    assert (
        nothing["run"],
        nothing["report"],
        nothing["trials_done"],
        nothing["trials_planned"],
    ) == (None, None, 0, planned)
    early = jane.post(f"/api/studies/{sid}/verdicts")
    assert early.status_code == 400 and "run all trials first" in early.json()["detail"]
    for k in range(planned):
        study_jobs.save_trial(
            conn,
            sid,
            {"entry_rsi": k},
            f"h{k}",
            "DONE",
            NOW,
            metrics={"sharpe": 1.0},
            returns=[0.01],
        )
    assert viewer.post(f"/api/studies/{sid}/verdicts").status_code == 403
    rid = jane.post(f"/api/studies/{sid}/verdicts").json()["run_id"]
    assert jane.post(f"/api/studies/{sid}/verdicts").status_code == 400  # one active job per study
    v = jane.get(f"/api/studies/{sid}/verdict").json()
    assert (v["run"]["run_id"], v["run"]["kind"], v["run"]["status"], v["trials_done"]) == (
        rid,
        "verdict",
        "QUEUED",
        planned,
    )
    assert (
        jane.get(f"/api/studies/{sid}/results").json()["run"] is None
    )  # the trials panel does not show it
    assert audit_actions_like(conn, "study.verdict%") == ["study.verdict_requested"]
    assert jane.post("/api/studies/9999/verdicts").status_code == 404
    assert jane.get("/api/studies/9999/verdict").status_code == 404


def test_the_holdout_can_be_requested_only_after_a_passing_verdict_and_only_by_someone_who_may(env):
    from algo.backtest.validation.gates import Evidence, Thresholds, evaluate
    from algo.backtest.validation.registry import save_report

    conn, app = env
    jane, viewer = sign_in(app, "jane@example.com"), sign_in(app, "viewer@example.com")
    sid = jane.post("/api/studies", json=body()).json()["experiment_id"]
    assert viewer.post(f"/api/studies/{sid}/holdout").status_code == 403
    assert jane.post("/api/studies/9999/holdout").status_code == 404
    early = jane.post(f"/api/studies/{sid}/holdout")
    assert early.status_code == 400 and "passed every check" in early.json()["detail"]
    base = conn.execute(
        "INSERT INTO backtest_run (strategy_id,strategy_version,params,params_hash,code_version,reader_mode,config,cost_model,"
        "adjustment_versions,provisional_events,unapplied_events,blocked_instruments,unmodelled_events,accounting_complete,"
        "dividends_received,metrics,result_hash,created_at,ledger_reconciled,reconciliation,pnl) VALUES ('s','1','{}','p','c',"
        "'research','{}','{}','{}','[]','[]','[]','[]',true,0,'{}','rh',%s,true,'{}','{}') RETURNING run_id", (NOW,)).fetchone()[0]  # fmt: skip
    ev = Evidence()
    rid = save_report(
        conn,
        sid,
        base,
        evaluate(ev, Thresholds(*([0.0] * 12)), "confirmed"),
        ev,
        1,
        NOW,
        refs={"chosen": {}},
    )
    failing = jane.post(f"/api/studies/{sid}/holdout")
    assert failing.status_code == 400  # the verdict failed (missing evidence)
    conn.execute("UPDATE validation_report SET passed=true WHERE report_id=%s", (rid,))
    queued = jane.post(f"/api/studies/{sid}/holdout").json()["run_id"]
    v = jane.get(f"/api/studies/{sid}/verdict").json()
    assert (v["holdout_run"]["run_id"], v["holdout_run"]["kind"], v["holdout"]) == (
        queued,
        "holdout",
        None,
    )
    assert v["run"] is None  # the verdict panel's own job is separate
    conn.execute("UPDATE experiment SET holdout_opened_at=%s WHERE experiment_id=%s", (NOW, sid))
    conn.execute("UPDATE study_run SET status='DONE' WHERE run_id=%s", (queued,))
    assert "already been opened" in jane.post(f"/api/studies/{sid}/holdout").json()["detail"]
    assert audit_actions_like(conn, "study.holdout%") == ["study.holdout_requested"]


def test_a_registration_while_the_research_lock_is_not_anchored_is_a_409_not_a_crash(env):
    conn, app = env
    conn.execute("ALTER TABLE research_lock DISABLE TRIGGER research_lock_no_change")
    conn.execute("DELETE FROM research_lock")  # the lock is not anchored
    trader = sign_in(app, "jane@example.com")
    r = trader.post("/api/studies", json=body())
    assert r.status_code == 409 and "research is locked" in r.json()["detail"]


def test_families_are_listed_for_research_and_started_only_by_an_explicit_audited_decision(env):
    conn, app = env
    viewer, trader = sign_in(app, "viewer@example.com"), sign_in(app, "jane@example.com")
    got = viewer.get("/api/families").json()["families"]
    assert [f["name"] for f in got] == ["Studies registered before research families"] and got[0][
        "trials"
    ] == 0
    new = {"name": "Value", "hypothesis": "Cheap, profitable companies beat the index over three years.",
           "justification": "Trades cross-sectional value, a different mechanism from the trend and pullback families."}  # fmt: skip
    assert viewer.post("/api/families", json=new).status_code == 403
    r = trader.post("/api/families", json=new)
    assert r.status_code == 200 and r.json()["family_id"] > 1
    assert trader.post("/api/families", json=new).status_code == 400  # the name is taken
    assert (
        trader.post(
            "/api/families", json={**new, "name": "Thin", "justification": "short"}
        ).status_code
        == 400
    )
    assert [f["name"] for f in viewer.get("/api/families").json()["families"]] == [
        "Studies registered before research families",
        "Value",
    ]
    assert "family.created" in [a for a in audit_actions_all(conn)]
    assert [f["name"] for f in viewer.get("/api/studies/options").json()["families"]][-1] == "Value"


def test_a_study_without_a_family_or_with_an_unknown_one_is_a_400_that_says_so(env):
    _, app = env
    trader = sign_in(app, "jane@example.com")
    assert trader.post("/api/studies", json=body(family_id=None)).status_code == 400
    r = trader.post("/api/studies", json=body(family_id=9999))
    assert r.status_code == 400 and "no research family 9999" in r.json()["detail"]
    assert trader.post("/api/studies", json=body(family_id=1)).status_code == 200


def audit_actions_all(conn):
    return [r[0] for r in conn.execute("SELECT action FROM portal_audit ORDER BY audit_id")]


def test_a_trader_backtests_a_generated_definition_in_one_click_and_a_viewer_cannot(env):
    from algo.factory import generate
    from algo.factory import registry as freg

    conn, app = env
    defn = generate.definition_for(
        generate.Hypothesis(1, 1, "ret_20d", "1", 20, "POSITIVE", 0.05, 0.001)
    )
    freg.register(conn, defn, by="agent", reason="generated", now=NOW)
    url = f"/api/strategies/definitions/{defn.strategy_id}/1/study"
    assert sign_in(app, "viewer@example.com").post(url).status_code == 403
    c = sign_in(app, "jane@example.com")
    r = c.post(url)
    assert r.status_code == 200, r.text
    eid = r.json()["experiment_id"]
    assert c.get(f"/api/studies/{eid}").json()["spec"]["strategy_id"] == "dsl"
    assert c.post(url).status_code == 400  # a run is already waiting
    assert c.post("/api/strategies/definitions/ALPHA_NOPE_H1/1/study").status_code == 404
    assert "study.registered" in audit_actions(conn)
