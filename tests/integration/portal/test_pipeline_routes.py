# ruff: noqa: E501
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from algo.api import pipeline_routes as p
from algo.backtest.validation import registry
from algo.core.clock import SimClock
from algo.data.store.migrate import migrate
from tests.support.portal import add_user, enrol_second_factor, make_app, settings, sign_in
from tests.support.research_lock import anchor_open_lock

START = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)
DEV_OK = {"passed": True, "failed": []}
INNER_OK = {"passed": True, "failed": []}


def stage(dev=None, inner=None, outer=None, paper=None, running=None, ended=None):
    s = p.summarise(dev, inner, outer, paper, running, ended)
    return s["stage"], s["outcome"], s["why"]


def test_a_strategy_that_did_not_start_is_waiting_or_running_in_development():
    assert stage()[:2] == ("development", "waiting")
    assert stage(running="trials running") == ("development", "running", "trials running")


def test_a_development_failure_names_the_gates_that_failed():
    s, o, why = stage({"passed": False, "failed": ["oos_sharpe", "beats_benchmark"]})
    assert (s, o) == ("development", "stopped") and "oos_sharpe, beats_benchmark" in why


def test_a_passed_development_waits_for_then_stops_at_the_inner_holdout():
    assert stage(DEV_OK)[:2] == ("inner", "waiting")
    assert stage(DEV_OK, running="holdout running")[:2] == ("inner", "running")
    s, o, why = stage(DEV_OK, {"passed": False, "failed": ["holdout_beats_benchmark"]})
    assert (
        (s, o) == ("inner", "stopped")
        and "holdout_beats_benchmark" in why
        and "Not yet submitted" in why
    )
    assert stage(DEV_OK, INNER_OK)[:2] == (
        "inner",
        "waiting",
    )  # passed, not yet submitted to the outer window


def test_the_outer_holdout_decides_paper_and_names_the_failed_checks():
    ok = {"overall": "PASS", "checks": []}
    assert stage(DEV_OK, INNER_OK, ok, "ready")[:2] == ("paper", "ready")
    assert stage(DEV_OK, INNER_OK, ok, "failed_holdout")[:2] == (
        "outer",
        "waiting",
    )  # passed, but the paper gate has not let it through
    bad = {
        "overall": "FAIL",
        "checks": [
            {"gate": "holdout_sharpe", "verdict": "FAIL"},
            {"gate": "holdout_drawdown", "verdict": "PASS"},
        ],
    }
    s, o, why = stage(
        DEV_OK, None, bad
    )  # a strategy may skip the inner holdout's verdict: the outer one still decides
    assert (
        (s, o) == ("outer", "stopped") and "holdout_sharpe" in why and "holdout_drawdown" not in why
    )
    assert stage(DEV_OK, INNER_OK, {"overall": "INCOMPLETE", "checks": []})[:2] == (
        "outer",
        "waiting",
    )


def test_failed_lists_every_gate_that_is_not_a_pass_and_cagr_is_per_year():
    assert p.failed(
        [
            {"name": "a", "status": "PASS"},
            {"name": "b", "status": "FAIL"},
            {"name": "c", "status": "INSUFFICIENT_EVIDENCE"},
        ]
    ) == ["b", "c"]
    assert p._cagr(1.0, 252) == pytest.approx(1.0)  # doubled in exactly a year
    assert p._cagr(3.0, 504) == pytest.approx(1.0)  # quadrupled in two years
    assert p._cagr(None, 252) is None and p._cagr(0.5, None) is None and p._cagr(-1.0, 252) is None


@pytest.fixture
def env(conn, pg_url, tmp_path):
    migrate(conn)
    anchor_open_lock(conn)
    clock = SimClock(START)
    return conn, make_app(pg_url, tmp_path, portal=settings(clock)), clock


@pytest.mark.integration
def test_the_pipeline_is_open_to_researchers_and_shows_the_outer_window_to_the_owner_only(env):
    conn, app, clock = env
    assert TestClient(app).get("/api/pipeline").status_code == 401
    add_user(
        conn, clock, "VIEWER", "viewer@example.com"
    )  # research:read is enough to see the pipeline
    r = sign_in(app, "viewer@example.com").get("/api/pipeline")
    assert isinstance(r.json()["code_dirty"], bool)
    assert r.status_code == 200 and r.json() == {
        "rows": [],
        "outer_visible": False,
        "code_dirty": r.json()["code_dirty"],
    }
    add_user(conn, clock, "ADMIN", "boss@example.com")
    boss = sign_in(app, "boss@example.com")
    enrol_second_factor(boss, clock)
    assert boss.get("/api/pipeline").json()["outer_visible"] is True


@pytest.mark.integration
def test_unrun_studies_are_listed_by_family_until_they_have_a_run(env):
    conn, app, clock = env
    uid = add_user(conn, clock, "TRADER", "t@example.com")
    c = sign_in(app, "t@example.com")
    assert c.get("/api/pipeline/unrun").json() == {"families": []}
    fid = registry.create_family(
        conn,
        name="Tech",
        hypothesis="technical rules that work",
        justification="a different idea from the others",
        created_by=uid,
        now=START,
    )

    def mk(name):
        return registry.register(
            conn, name=name, strategy_id="screener", hypothesis="h", style="long_only", param_ranges={},
            holdout=(START.date(), START.date()), now=START, study={"combinations": []}, family_id=fid,
        )  # fmt: skip

    a, b = mk("A study"), mk("B study")
    got = c.get("/api/pipeline/unrun").json()["families"]
    assert [(f["name"], [s["name"] for s in f["studies"]]) for f in got] == [
        ("Tech", ["A study", "B study"])
    ]
    conn.execute(
        "INSERT INTO study_run (experiment_id, status, requested_by, created_at) VALUES (%s,'QUEUED',%s,%s)",
        (a, uid, START),
    )
    assert [
        s["experiment_id"] for s in c.get("/api/pipeline/unrun").json()["families"][0]["studies"]
    ] == [b]


def test_a_stopped_run_reads_as_stopped_not_waiting():
    assert stage(ended="The trials run was cancelled.") == (
        "development",
        "stopped",
        "The trials run was cancelled.",
    )
    assert stage(DEV_OK, ended="The holdout run failed: x")[:2] == ("inner", "stopped")
    assert stage(DEV_OK, INNER_OK, ended="ignored once the inner holdout has its result")[:2] == (
        "inner",
        "waiting",
    )


@pytest.mark.integration
def test_a_corrected_re_registration_replaces_the_study_it_supersedes_on_the_page_and_in_the_popup(
    env,
):
    conn, app, clock = env
    uid = add_user(conn, clock, "TRADER", "t@example.com")
    c = sign_in(app, "t@example.com")
    fid = registry.create_family(
        conn,
        name="Tech",
        hypothesis="technical rules that work",
        justification="a different idea from the others",
        created_by=uid,
        now=START,
    )

    def mk(name, rule):
        return registry.register(
            conn, name=name, strategy_id="screener", hypothesis="h", style="long_only", param_ranges={},
            holdout=(START.date(), START.date()), now=START, study={"spec": {"screen": rule}}, family_id=fid,
        )  # fmt: skip

    old, other = mk("Golden cross", {"sort": "a"}), mk("Breakout", {"sort": "b"})
    new = mk(
        "Golden cross 2016-2022", {"sort": "a"}
    )  # the same rule, registered again with corrected settings
    conn.execute(
        "INSERT INTO study_run (experiment_id, kind, status, requested_by, created_at, error) VALUES (%s,'trials','CANCELLED',%s,%s,'x')",
        (old, uid, START),
    )
    names = {r["name"]: r for r in c.get("/api/pipeline").json()["rows"]}
    assert set(names) == {
        "Golden cross 2016-2022",
        "Breakout",
    }  # the older Golden cross is gone from the page
    assert (
        names["Golden cross 2016-2022"]["experiment_id"] == new
        and names["Golden cross 2016-2022"]["outcome"] == "waiting"
    )
    assert [s["name"] for s in c.get("/api/pipeline/unrun").json()["families"][0]["studies"]] == [
        "Breakout",
        "Golden cross 2016-2022",
    ]
    assert other < new
    conn.execute(
        "INSERT INTO study_run (experiment_id, kind, status, requested_by, created_at, error) VALUES (%s,'trials','FAILED',%s,%s,'boom')",
        (new, uid, START),
    )
    row = next(r for r in c.get("/api/pipeline").json()["rows"] if r["experiment_id"] == new)
    assert (row["outcome"], row["why"]) == ("stopped", "The trials run failed: boom")
