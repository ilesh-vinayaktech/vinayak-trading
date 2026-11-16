# ruff: noqa: E501
"""The read-only research-intelligence API: every number comes from rows the Phase 1 to 5 parts wrote."""

import random
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from algo.alpha import registry as alpha_registry
from algo.alpha.discover import Evidence
from algo.data.store.migrate import migrate
from algo.features import store as feature_store
from algo.learning import memory
from algo.portfolio import audit
from tests.support.portal import open_app

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


def series(seed, vol, n=60):
    rng = random.Random(seed)
    return [rng.gauss(0.0005, vol) for _ in range(n)]


@pytest.fixture
def client(conn, pg_url, tmp_path):
    migrate(conn)
    conn.commit()
    return TestClient(open_app(pg_url, tmp_path)), conn


def test_an_empty_database_gives_an_honest_empty_overview(client):
    c, _ = client
    body = c.get("/api/intel/overview").json()
    assert body["features"] == {"by_status": {}} and body["alpha"] == {
        "tests_ever_run": 0,
        "by_status": {},
    }
    assert body["factory"] == {"definitions": 0, "experiments": 0, "trials": 0} and body[
        "notes"
    ] == {"total": 0}
    assert body["health"] == [] and body["allocation"] is None
    assert c.get("/api/intel/alpha").json() == {"hypotheses": []}
    assert c.get("/api/intel/notes").json() == {"notes": []}
    assert c.get("/api/intel/allocations").json() == {"allocations": []}


def test_the_overview_and_lists_show_what_the_parts_recorded(client):
    c, conn = client
    feature_store.register_all(conn, NOW)
    good = Evidence("ret_5d", "1", 5, 500, 150.0, 0.05, 0.1, 0.5, 0.6, 4.0, 0.0001)
    bad = Evidence("ret_20d", "1", 20, 500, 150.0, 0.0, 0.1, 0.0, 0.5, 0.0, 0.9)
    alpha_registry.record(conn, [good, bad], "d" * 64, NOW)
    memory.add(conn, "DECISION", "capital", "Paper capital Rs 1 lakh", by="owner", now=NOW)
    memory.sync_alpha(conn, now=NOW)
    r = {"A": series(1, 0.01), "B": series(2, 0.02), "C": series(3, 0.015), "D": series(4, 0.01)}
    audit.recommend_and_record(
        conn, r, dict.fromkeys(r, "OK"), by="jane", now=NOW, method="EQUAL_RISK"
    )
    conn.execute(
        "INSERT INTO dq_result (run_at, check_name, scope, subject, status, detail) VALUES (%s,'degradation','paper u1 vs backtest run 1',NULL,'FAIL','DEGRADED: mean return -0.5%% a day')",
        (NOW,),
    )
    conn.commit()

    o = c.get("/api/intel/overview").json()
    assert o["features"]["by_status"] == {"DRAFT": 35}
    assert o["alpha"] == {"tests_ever_run": 2, "by_status": {"CANDIDATE": 1, "REJECTED": 1}}
    assert o["notes"] == {"total": 3}
    assert o["health"][0]["status"] == "FAIL" and o["health"][0]["detail"].startswith("DEGRADED")
    assert (
        o["allocation"]["method"] == "EQUAL_RISK"
        and o["allocation"]["by"] == "jane"
        and sum(o["allocation"]["weights"].values()) <= 1.0
    )

    hyp = c.get("/api/intel/alpha").json()["hypotheses"]
    assert [(h["feature"], h["status"], h["direction"]) for h in hyp] == [
        ("ret_20d", "REJECTED", None),
        ("ret_5d", "CANDIDATE", "POSITIVE"),
    ]
    only = c.get("/api/intel/alpha", params={"status": "CANDIDATE"}).json()["hypotheses"]
    assert (
        [h["feature"] for h in only] == ["ret_5d"]
        and only[0]["mean_ic"] == 0.05
        and only[0]["horizon"] == 5
    )

    assert [n["kind"] for n in c.get("/api/intel/notes").json()["notes"]] == [
        "FAILURE",
        "FINDING",
        "DECISION",
    ]  # newest first
    assert [
        n["subject"] for n in c.get("/api/intel/notes", params={"q": "capital"}).json()["notes"]
    ] == ["capital"]
    assert [
        n["kind"] for n in c.get("/api/intel/notes", params={"kind": "FAILURE"}).json()["notes"]
    ] == ["FAILURE"]
    al = c.get("/api/intel/allocations").json()["allocations"]
    assert len(al) == 1 and al[0]["risk_contribution"] and al[0]["notes"] is not None


def test_bad_filters_are_refused_and_nothing_can_be_written_through_this_api(client):
    c, conn = client
    assert c.get("/api/intel/alpha", params={"status": "MAYBE"}).status_code == 422
    assert c.get("/api/intel/notes", params={"kind": "OPINION"}).status_code == 422
    assert c.get("/api/intel/alpha", params={"limit": 0}).status_code == 422
    for path in ("overview", "alpha", "notes", "allocations"):
        assert c.post(f"/api/intel/{path}", json={}).status_code == 405
        assert c.delete(f"/api/intel/{path}").status_code == 405
    assert conn.execute("SELECT count(*) FROM research_note").fetchone() == (0,)


def test_progress_shows_running_jobs_first_with_elapsed_quiet_time_and_whether_the_process_is_alive(
    client,
):
    import os
    from datetime import timedelta

    c, conn = client
    assert c.get("/api/intel/progress").json() == {"jobs": []}
    now = c.app.state.portal.clock.now()
    mine, gone = os.getpid(), 2**22 + 99
    rows = [
        (
            "done_job",
            "Finished job",
            mine,
            "DONE",
            3,
            3,
            "finished",
            "ok",
            now - timedelta(hours=2),
            now - timedelta(hours=1),
            now - timedelta(hours=1),
        ),
        (
            "live",
            "Live job",
            mine,
            "RUNNING",
            2,
            12,
            "checking ret_5d",
            "look-ahead test 1 of 5",
            now - timedelta(minutes=30),
            now - timedelta(seconds=20),
            None,
        ),
        (
            "quiet",
            "Quiet job",
            mine,
            "RUNNING",
            0,
            4,
            "reading prices",
            "",
            now - timedelta(hours=1),
            now - timedelta(minutes=31),
            None,
        ),
        (
            "dead",
            "Dead job",
            gone,
            "RUNNING",
            1,
            4,
            "x",
            "",
            now - timedelta(minutes=5),
            now - timedelta(seconds=5),
            None,
        ),
    ]
    for r in rows:
        conn.execute(
            "INSERT INTO job_progress (job, label, pid, status, done, total, phase, message, started_at, updated_at, finished_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            r,
        )
    conn.commit()
    jobs = {j["job"]: j for j in c.get("/api/intel/progress").json()["jobs"]}
    assert [j["job"] for j in c.get("/api/intel/progress").json()["jobs"]][
        -1
    ] == "done_job"  # finished jobs come after the running ones
    live = jobs["live"]
    assert (
        live["done"],
        live["total"],
        live["phase"],
        live["message"],
        live["elapsed_s"],
        live["quiet_s"],
        live["alive"],
        live["stalled"],
    ) == (2, 12, "checking ret_5d", "look-ahead test 1 of 5", 1800, 20, True, False)
    assert (
        jobs["quiet"]["stalled"] is True and jobs["quiet"]["alive"] is True
    )  # silent for 31 minutes: past the 30 allowed
    assert jobs["dead"]["stalled"] is True and jobs["dead"]["alive"] is False  # the process is gone
    finished = jobs["done_job"]
    assert (
        finished["status"],
        finished["elapsed_s"],
        finished["quiet_s"],
        finished["alive"],
        finished["stalled"],
    ) == ("DONE", 3600 - 0, None, None, False)
    assert c.get("/api/intel/progress", params={"limit": 0}).status_code == 422
    assert c.post("/api/intel/progress", json={}).status_code == 405


def stage(body, key):
    return next(s for s in body["stages"] if s["key"] == key)


def test_the_funnel_is_all_zeros_and_marks_the_unlinked_stages_on_an_empty_database(client):
    c, _ = client
    body = c.get("/api/intel/funnel").json()
    assert [s["key"] for s in body["stages"]] == [
        "features",
        "alpha",
        "definitions",
        "trials",
        "validation",
        "paper",
    ]
    assert all(
        s["entered"] == 0 and s["passed"] == 0 and s["dropped"] == [] for s in body["stages"]
    )
    assert [s["connected"] for s in body["stages"]] == [True, True, True, True, True, False]


def test_the_funnel_counts_what_moved_on_and_why_the_rest_dropped(client):
    c, conn = client
    feature_store.register_all(conn, NOW)
    fids = [
        r[0]
        for r in conn.execute(
            "SELECT feature_id FROM feature_definition ORDER BY feature_id"
        ).fetchall()
    ]
    # 35 features: 3 USABLE, 2 BLOCKED, 2 DRAFT whose last validation failed, 28 DRAFT never validated
    for f in fids[:3]:
        conn.execute(
            "INSERT INTO feature_status (feature_id, status, reason, set_by, at) VALUES (%s,'USABLE','ok','t',%s)",
            (f, NOW),
        )
    for f in fids[3:5]:
        conn.execute(
            "INSERT INTO feature_status (feature_id, status, reason, set_by, at) VALUES (%s,'BLOCKED','no','t',%s)",
            (f, NOW),
        )
    for f in fids[5:7]:
        conn.execute(
            "INSERT INTO feature_validation (feature_id, dataset_sha256, passed, report, created_by, created_at) VALUES (%s,%s,FALSE,'{}','t',%s)",
            (f, "a" * 64, NOW),
        )
    conn.execute(
        "INSERT INTO feature_validation (feature_id, dataset_sha256, passed, report, created_by, created_at) VALUES (%s,%s,TRUE,'{}','t',%s)",
        (fids[0], "a" * 64, NOW),
    )
    strong = Evidence("ret_5d", "1", 5, 500, 150.0, 0.05, 0.1, 0.5, 0.6, 4.0, 0.0001)
    flat = Evidence(
        "ret_20d", "1", 20, 500, 150.0, 0.0001, 0.1, 0.001, 0.5, 0.01, 0.0001
    )  # significant but a tiny effect
    noisy = Evidence(
        "ret_60d", "1", 60, 500, 150.0, 0.05, 0.1, 0.5, 0.5, 1.0, 0.9
    )  # a real-sized effect that is not significant
    none = Evidence("ret_1d", "1", 1, 3, 150.0, None, None, None, None, None, None)
    alpha_registry.record(conn, [strong, flat, noisy, none], "d" * 64, NOW)
    conn.commit()
    body = c.get("/api/intel/funnel").json()
    f = stage(body, "features")
    assert (f["entered"], f["passed"]) == (35, 3)
    assert {d["reason"]: d["count"] for d in f["dropped"]} == {
        "Failed validation": 2,
        "Waiting to be validated": 28,
        "Blocked": 2,
    }
    a = stage(body, "alpha")
    assert (a["entered"], a["passed"]) == (4, 1)
    assert {d["reason"]: d["count"] for d in a["dropped"]} == {
        "No result (too little data)": 1,
        "Effect too small to matter": 1,
        "Not significant after counting every test ever run": 1,
    }
    assert all(
        sum(d["count"] for d in s["dropped"]) == s["entered"] - s["passed"]
        for s in body["stages"]
        if s["connected"]
    )


def test_the_estimate_comes_from_how_long_finished_steps_took_and_says_when_it_cannot_give_one(
    client,
):
    import os
    from datetime import timedelta

    c, conn = client
    now = c.app.state.portal.clock.now()
    me = os.getpid()

    def add(job, status, done, total, first, last, uniform=True):
        conn.execute(
            "INSERT INTO job_progress (job, label, pid, status, done, total, phase, message, started_at, updated_at, finished_at, first_done_at, last_done_at, first_done_count, uniform) VALUES (%s,%s,%s,%s,%s,%s,'p','',%s,%s,%s,%s,%s,%s,%s)",
            (
                job,
                job,
                me,
                status,
                done,
                total,
                now - timedelta(hours=1),
                now - timedelta(seconds=5),
                None if status == "RUNNING" else now,
                first,
                last,
                None if first is None else 1,
                uniform,
            ),
        )

    m = timedelta(minutes=1)
    add(
        "ok", "RUNNING", 4, 12, now - 40 * m, now - 10 * m
    )  # 3 gaps in 30 min: 10 min a step; 8 steps left minus 10 min already spent in this one
    add("waiting", "RUNNING", 1, 12, now - 10 * m, now - 10 * m)
    add("none_yet", "RUNNING", 0, 12, None, None)
    add("uneven", "RUNNING", 3, 4, now - 30 * m, now - 5 * m, uniform=False)
    add(
        "overrun", "RUNNING", 3, 4, now - 20 * m, now - 12 * m
    )  # 4 min a step, but this step has run 12 min
    add("finished", "DONE", 12, 12, now - 50 * m, now - 5 * m)
    conn.commit()
    jobs = {j["job"]: j for j in c.get("/api/intel/progress").json()["jobs"]}
    assert (jobs["ok"]["estimate"], jobs["ok"]["per_step_s"], jobs["ok"]["eta_s"]) == (
        "ok",
        600,
        8 * 600 - 600,
    )
    assert (
        jobs["waiting"]["estimate"],
        jobs["waiting"]["per_step_s"],
        jobs["waiting"]["eta_s"],
    ) == ("waiting", None, None)
    assert jobs["none_yet"]["estimate"] == "waiting"
    assert (jobs["uneven"]["estimate"], jobs["uneven"]["eta_s"]) == ("uneven", None)
    assert (
        jobs["overrun"]["estimate"],
        jobs["overrun"]["per_step_s"],
        jobs["overrun"]["eta_s"],
    ) == ("overrun", 240, None)
    assert (jobs["finished"]["estimate"], jobs["finished"]["eta_s"]) == ("none", None)


def _report(passed, reasons, share="0.989657", identical=True, stored_ok=True, violations=0):
    return {
        "passed": passed, "reasons": reasons, "min_coverage": "0.90",
        "coverage": {"share": share, "eligible": 100, "valued": 99},
        "recompute": {"identical": identical, "months": 3, "stored_months_checked": 2, "stored_match": stored_ok},
        "lookahead": {"cuts": [], "checks": 40, "violations": violations},
    }  # fmt: skip


def test_the_features_list_shows_what_each_measures_its_status_and_why_the_last_validation_passed_or_failed(
    client,
):
    from psycopg.types.json import Jsonb

    from algo.features import registry as feature_registry

    c, conn = client
    body = c.get("/api/intel/features").json()["features"]
    assert len(body) == len(feature_registry.DEFINITIONS) == 35
    assert all(
        f["status"] == "NOT_REGISTERED" and f["validation"] is None and f["validations"] == 0
        for f in body
    )  # defined in code, nothing stored yet
    ret5 = next(f for f in body if f["name"] == "ret_5d")
    assert (
        ret5["measures"] == "close[t] / close[t-n] - 1"
        and ret5["unit"] == "fraction"
        and ret5["inputs"] == ["close"]
        and ret5["warmup"] == 6
    )

    feature_store.register_all(conn, NOW)
    ids = dict(conn.execute("SELECT name, feature_id FROM feature_definition").fetchall())
    conn.execute(
        "INSERT INTO feature_status (feature_id, status, reason, set_by, at) VALUES (%s,'USABLE','validated','agent',%s)",
        (ids["ret_5d"], NOW),
    )
    good = _report(True, [])
    bad = _report(
        False,
        [
            "coverage 0.8000 is below the minimum 0.90",
            "look-ahead: 3 value(s) changed when later data was removed",
        ],
        share="0.800000",
        violations=3,
    )
    for name, rep in (("ret_5d", good), ("vol_20d", bad)):
        conn.execute(
            "INSERT INTO feature_validation (feature_id, dataset_sha256, passed, report, created_by, created_at) VALUES (%s,%s,%s,%s,'agent',%s)",
            (ids[name], "a" * 64, rep["passed"], Jsonb(rep), NOW),
        )
    conn.execute(
        "INSERT INTO feature_validation (feature_id, dataset_sha256, passed, report, created_by, created_at) VALUES (%s,%s,FALSE,%s,'agent',%s)",
        (ids["vol_20d"], "a" * 64, Jsonb(_report(False, ["old failure"])), NOW),
    )
    conn.commit()
    by = {f["name"]: f for f in c.get("/api/intel/features").json()["features"]}
    ok = by["ret_5d"]
    assert (ok["status"], ok["status_reason"], ok["validations"]) == ("USABLE", "validated", 1)
    assert (
        ok["validation"]["passed"] is True
        and ok["validation"]["reasons"] == []
        and all(chk["ok"] for chk in ok["validation"]["checks"].values())
    )
    assert (
        ok["validation"]["checks"]["coverage"]["detail"]
        == "98.97% of eligible days have a value (minimum 90%)"
    )
    assert (
        ok["validation"]["checks"]["no_lookahead"]["detail"]
        == "0 value(s) changed when later data was removed, in 40 checks"
    )
    failed = by["vol_20d"]
    assert (failed["status"], failed["validations"]) == (
        "DRAFT",
        2,
    )  # registered, never made usable, validated twice
    v = failed["validation"]
    assert v["passed"] is False and v["reasons"] == ["old failure"]  # the LATEST report wins
    assert (
        by["ret_20d"]["status"] == "DRAFT"
        and by["ret_20d"]["validation"] is None
        and by["ret_20d"]["validations"] == 0
    )


def test_the_failure_reasons_light_up_exactly_the_checks_that_failed(client):
    from psycopg.types.json import Jsonb

    c, conn = client
    feature_store.register_all(conn, NOW)
    fid = conn.execute("SELECT feature_id FROM feature_definition WHERE name='ret_20d'").fetchone()[
        0
    ]
    rep = _report(
        False,
        [
            "coverage 0.8000 is below the minimum 0.90",
            "recomputing from an independent read gave different values",
            "a materialised month differs from the recomputation",
            "look-ahead: 3 value(s) changed when later data was removed",
        ],
        share="0.8",
        identical=False,
        stored_ok=False,
        violations=3,
    )
    conn.execute(
        "INSERT INTO feature_validation (feature_id, dataset_sha256, passed, report, created_by, created_at) VALUES (%s,%s,FALSE,%s,'agent',%s)",
        (fid, "a" * 64, Jsonb(rep), NOW),
    )
    conn.commit()
    checks = next(
        f for f in c.get("/api/intel/features").json()["features"] if f["name"] == "ret_20d"
    )["validation"]["checks"]
    assert {k: v["ok"] for k, v in checks.items()} == {
        "coverage": False,
        "reproducible": False,
        "stored_match": False,
        "no_lookahead": False,
    }
    assert (
        checks["reproducible"]["detail"]
        == "recomputing from an independent read gave different values"
    )


def test_a_fundamental_features_coverage_says_how_many_companies_it_could_exist_for(client):
    from psycopg.types.json import Jsonb

    c, conn = client
    feature_store.register_all(conn, NOW)
    fid = conn.execute(
        "SELECT feature_id FROM feature_definition WHERE name='fund_roe'"
    ).fetchone()[0]
    rep = _report(True, [], share="0.87")
    rep["coverage"]["universe"] = {"instruments": 2600, "with_filings": 454}
    conn.execute(
        "INSERT INTO feature_validation (feature_id, dataset_sha256, passed, report, created_by, created_at) VALUES (%s,%s,TRUE,%s,'agent',%s)",
        (fid, "a" * 64, Jsonb(rep), NOW),
    )
    conn.commit()
    by = {f["name"]: f for f in c.get("/api/intel/features").json()["features"]}
    assert (
        by["fund_roe"]["validation"]["checks"]["coverage"]["detail"]
        == "87.00% of eligible days have a value (minimum 90%); counted only for the 454 of 2600 companies that have filings"
    )
    assert by["fund_roe"]["family"] == "fundamental"


def test_a_study_of_a_generated_definition_shows_in_the_trial_and_validation_stages(client):
    from datetime import date

    from algo.backtest.validation import registry as vreg

    c, conn = client
    eid = vreg.register(
        conn, name="s", strategy_id="dsl", hypothesis="h" * 25, style="long_only",
        param_ranges={"entry_share": [10, 20]}, holdout=(date(2023, 10, 1), date(2024, 12, 31)), now=NOW,
        study={"spec": {"definition": {"strategy_id": "ALPHA_X", "version": 1}}}, owner_user_id=None, family_id=1,
    )  # fmt: skip
    for i, status in enumerate(("DONE", "FAILED")):
        conn.execute(
            "INSERT INTO study_trial (experiment_id, variant, params, params_hash, status, finished_at) VALUES (%s,'base','{}',%s,%s,%s)",
            (eid, f"h{i}", status, NOW),
        )
    conn.commit()
    body = c.get("/api/intel/funnel").json()
    t, v = stage(body, "trials"), stage(body, "validation")
    assert (t["entered"], t["passed"]) == (2, 1) and stage(body, "definitions")["passed"] == 1
    assert (v["entered"], v["passed"]) == (1, 0)
    assert {d["reason"]: d["count"] for d in v["dropped"]} == {"Not judged yet": 1}
