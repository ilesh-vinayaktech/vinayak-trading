# ruff: noqa: E501
import dataclasses
from datetime import UTC, date, datetime
from decimal import Decimal as D

import pytest

from algo.data import freeze as freeze_mod
from algo.data.readiness import Readiness
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.features import job, registry, store, validation
from algo.features._shared import q
from algo.research import holdout_lock
from tests.integration.features.test_store import LOCK, NOW, sessions
from tests.support.bt import put_bars
from tests.support.research_lock import write_lock_file

pytestmark = pytest.mark.integration
JAN = date(2026, 1, 1)


@pytest.fixture
def world(conn, monkeypatch, tmp_path):
    migrate(conn)
    monkeypatch.setattr(holdout_lock, "LOCK_FILE", write_lock_file(tmp_path / "lock.json", LOCK))
    holdout_lock.anchor(conn, LOCK, by="owner", reason="test", now=NOW)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    ids = [repo.add_instrument(x, s) for s in ("AAA", "BBB")]
    days = sessions()
    for k, i in enumerate(ids):
        put_bars(conn, i, {d: 100 + 100 * k + n for n, d in enumerate(days)})
    store.register_all(conn, NOW)
    fid = freeze_mod.take(conn, "nse", days[-1], datetime(2026, 11, 7, tzinfo=UTC), "test freeze")
    return conn, ids, fid


def validate(conn, fid, name="ret_5d", **kw):
    return validation.validate(conn, name, "1", fid, JAN, **kw)


def test_a_sound_feature_passes_is_reported_and_becomes_usable_citing_the_report(world):
    conn, ids, fid = world
    r = validate(conn, fid)
    assert r["passed"] is True and r["reasons"] == []
    assert r["months"] == ["2026-01", "2026-02"] and r["instruments"] == 2  # March is the holdout
    c = r["coverage"]
    assert (
        c["eligible"] == c["valued"] > 0
        and c["share"] == "1"
        and c["warmup_absent"] == 0
        and c["missing_session_absent"] == 0
    )
    assert r["recompute"] == {
        "identical": True,
        "months": 2,
        "stored_months_checked": 0,
        "stored_match": True,
    }
    assert r["lookahead"]["violations"] == 0 and r["lookahead"]["checks"] > 0
    assert D(r["values"]["min"]) < D(r["values"]["max"])
    rid = validation.record(
        conn, "ret_5d", "1", job.dataset_sha256(conn, fid, ids), r, by="owner", now=NOW
    )
    assert store.status(conn, "ret_5d", "1") == "USABLE"
    reason = conn.execute(
        "SELECT reason FROM feature_status s JOIN feature_definition d USING (feature_id) WHERE d.name='ret_5d' ORDER BY status_id DESC LIMIT 1"
    ).fetchone()[0]
    assert f"validation report {rid}" in reason
    assert conn.execute(
        "SELECT passed, report->>'feature' FROM feature_validation WHERE report_id=%s", (rid,)
    ).fetchone() == (True, "ret_5d")


def test_a_feature_below_the_coverage_minimum_stays_draft_and_the_report_says_why(world):
    conn, ids, fid = world
    repo = InstrumentRepo(conn)
    ccc = repo.add_instrument(repo.add_exchange("XBSE", "IN", "Asia/Kolkata", "INR", "BSE"), "CCC")
    put_bars(
        conn, ccc, {d: 50 + n for n, d in enumerate(sessions()) if d.day % 2}
    )  # CCC trades on odd dates only: every 6-session window has a hole
    ids = [*ids, ccc]
    fid2 = freeze_mod.take(
        conn, "nse", sessions()[-2], datetime(2026, 11, 8, tzinfo=UTC), "with a sparse stock"
    )
    r = validate(conn, fid2)
    assert r["passed"] is False and any("coverage" in x for x in r["reasons"])
    assert D(r["coverage"]["share"]) < D("0.9") and r["coverage"]["missing_session_absent"] > 0
    rid = validation.record(
        conn, "ret_5d", "1", job.dataset_sha256(conn, fid2, ids), r, by="owner", now=NOW
    )
    assert store.status(conn, "ret_5d", "1") == "DRAFT"
    assert conn.execute(
        "SELECT passed FROM feature_validation WHERE report_id=%s", (rid,)
    ).fetchone() == (False,)
    r = validate(conn, fid2, min_coverage=D("0.1"))  # the owner sets the minimum
    assert r["passed"] is True


def test_a_feature_with_a_look_ahead_is_not_usable_however_complete_it_is(world, monkeypatch):
    conn, _, fid = world

    def leaky(sessions_, bars):
        out = {}
        for i, d in enumerate(sessions_[:-1]):
            if d in bars and sessions_[i + 1] in bars:
                out[d] = (
                    q(bars[sessions_[i + 1]].close / bars[d].close - 1),
                    bars[sessions_[i + 1]].available_at,
                )
        return out

    monkeypatch.setitem(
        registry.DEFINITIONS,
        "ret_5d",
        dataclasses.replace(registry.DEFINITIONS["ret_5d"], compute=leaky),
    )
    r = validate(conn, fid)
    assert (
        r["passed"] is False
        and r["lookahead"]["violations"] > 0
        and any("look-ahead" in x for x in r["reasons"])
    )


def test_a_stored_materialisation_that_differs_from_the_recomputation_fails_validation(world):
    conn, ids, fid = world
    sha = job.dataset_sha256(conn, fid, ids)
    fdef = conn.execute("SELECT feature_id FROM feature_definition WHERE name='ret_5d'").fetchone()[
        0
    ]
    conn.execute(
        "INSERT INTO feature_run (feature_id, month, dataset_sha256, code_commit, status, rows, result_sha256, started_at, finished_at) VALUES (%s,%s,%s,'x','complete',0,%s,%s,%s)",
        (fdef, JAN, sha, "0" * 64, NOW, NOW),
    )
    r = validate(conn, fid)
    assert (
        r["recompute"]["stored_months_checked"] == 1
        and r["recompute"]["stored_match"] is False
        and r["passed"] is False
    )
    # and a genuinely materialised month is checked and matches
    job.run(
        conn, fid, date(2026, 2, 1), NOW, "abc", ready=lambda c, n: Readiness()
    )  # nothing usable yet: writes nothing
    assert (
        conn.execute("SELECT count(*) FROM feature_run WHERE status='complete'").fetchone()[0] == 1
    )


def test_matching_stored_months_are_counted_and_blocked_status_is_never_overridden(world):
    conn, ids, fid = world
    sha = job.dataset_sha256(conn, fid, ids)
    store.set_status(conn, "ret_5d", "1", "USABLE", by="owner", reason="seed", now=NOW)
    job.run(conn, fid, JAN, NOW, "abc", ready=lambda c, n: Readiness())
    r = validate(conn, fid)
    assert (
        r["recompute"]["stored_months_checked"] == 2
        and r["recompute"]["stored_match"] is True
        and r["passed"]
    )
    store.set_status(conn, "ret_5d", "1", "BLOCKED", by="owner", reason="input problem", now=NOW)
    validation.record(conn, "ret_5d", "1", sha, r, by="owner", now=NOW)
    assert store.status(conn, "ret_5d", "1") == "BLOCKED"  # a person unblocks it, a report does not


def test_the_validation_table_is_insert_only_and_an_empty_window_is_refused(world):
    conn, ids, fid = world
    r = validate(conn, fid)
    rid = validation.record(
        conn, "ret_5d", "1", job.dataset_sha256(conn, fid, ids), r, by="owner", now=NOW
    )
    import psycopg

    with pytest.raises(psycopg.errors.RaiseException, match="insert-only"):
        conn.execute("UPDATE feature_validation SET passed=false WHERE report_id=%s", (rid,))
    with pytest.raises(validation.ValidationError, match="no whole month"):
        validation.validate(conn, "ret_5d", "1", fid, date(2026, 3, 1))  # the holdout
    from uuid import uuid4

    with pytest.raises(validation.ValidationError, match="no such freeze"):
        validation.validate(conn, "ret_5d", "1", uuid4(), JAN)


def test_days_inside_the_warm_up_are_reported_as_such_and_do_not_count_against_coverage(world):
    conn, _, fid = world
    r = validation.validate(
        conn, "ret_5d", "1", fid, date(2025, 12, 1)
    )  # the data starts on 2025-12-01
    c = r["coverage"]
    assert (
        c["warmup_absent"] == 2 * 5
        and c["missing_session_absent"] == 0
        and c["share"] == "1"
        and r["passed"]
    )


def test_a_feature_that_does_not_recompute_identically_fails(world, monkeypatch):
    conn, _, fid = world
    real = registry.DEFINITIONS["ret_5d"].compute
    calls = []

    def drifting(sessions_, bars):
        calls.append(1)
        out = real(sessions_, bars)
        return {
            d: (v + len(calls), a) for d, (v, a) in out.items()
        }  # a different answer every time it is asked

    monkeypatch.setitem(
        registry.DEFINITIONS,
        "ret_5d",
        dataclasses.replace(registry.DEFINITIONS["ret_5d"], compute=drifting),
    )
    r = validate(conn, fid)
    assert (
        r["recompute"]["identical"] is False
        and r["passed"] is False
        and any("independent read" in x for x in r["reasons"])
    )


def test_reads_shared_across_features_give_the_same_report_and_are_read_only_once(
    world, monkeypatch
):
    conn, ids, fid = world
    alone = {n: validate(conn, fid, n) for n in ("ret_5d", "ret_20d")}
    reads_made = []
    real = validation._bars
    monkeypatch.setattr(validation, "_bars", lambda *a, **k: reads_made.append(1) or real(*a, **k))
    reads = validation.read_bars(conn, fid, JAN)
    assert len(reads_made) == 2  # the two independent reads, once
    shared = {n: validate(conn, fid, n, reads=reads) for n in ("ret_5d", "ret_20d")}
    assert len(reads_made) == 2  # no feature read prices again
    assert shared == alone and all(r["recompute"]["identical"] for r in shared.values())


def test_progress_is_reported_for_reads_months_and_each_look_ahead_test(world):
    conn, ids, fid = world
    seen = []
    validate(conn, fid, report=lambda phase, msg: seen.append((phase, msg)))
    phases = [p for p, _ in seen]
    assert (
        phases[:2] == ["reading prices", "reading prices"]
        and "first of two" in seen[0][1]
        and "second of two" in seen[1][1]
        and "2 instruments" in seen[0][1]
    )
    assert (
        "checking ret_5d",
        "recomputing every month from the first read (2 months, one pass)",
    ) in seen
    assert ("checking ret_5d", "recomputing every month from the second, independent read") in seen
    cuts = [m for p, m in seen if m.startswith("look-ahead tests")]
    assert (
        cuts and cuts[0] == "look-ahead tests: company 1 of 2, 3 cut dates each"
    )  # reported at the first company, then every 200
    quiet = []
    validation.read_bars(conn, fid, JAN, report=None)
    assert quiet == []  # reporting is optional


def test_reading_for_a_freeze_or_window_that_does_not_exist_is_refused(world):
    conn, ids, fid = world
    with pytest.raises(validation.ValidationError, match="no such freeze"):
        validation.read_bars(conn, __import__("uuid").uuid4(), JAN)
    with pytest.raises(validation.ValidationError, match="no whole month"):
        validation.read_bars(conn, fid, date(2030, 1, 1))


def test_the_script_validates_every_feature_from_one_shared_read_and_records_live_progress(
    world, pg_url, monkeypatch, capsys
):
    import runpy
    import sys
    from pathlib import Path

    conn, ids, fid = world
    conn.commit()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "validate_features.py",
            "--db",
            pg_url,
            "--from",
            "2026-01-01",
            "--dry-run",
            "ret_5d",
            "ret_20d",
        ],
    )
    reads_made = []
    real = validation._bars
    monkeypatch.setattr(validation, "_bars", lambda *a, **k: reads_made.append(1) or real(*a, **k))
    with pytest.raises(SystemExit) as stop:
        runpy.run_path(
            str(Path(__file__).parents[3] / "scripts/validate_features.py"), run_name="__main__"
        )
    assert (
        stop.value.code == 0 and len(reads_made) == 2
    )  # two reads for the two features together, not four
    out = capsys.readouterr().out
    assert "ret_5d: PASS" in out and "ret_20d: PASS" in out
    status, done, total, phase, message, label = conn.execute(
        "SELECT status, done, total, phase, message, label FROM job_progress"
    ).fetchone()
    assert (status, done, total, phase) == (
        "DONE",
        2,
        2,
        "finished",
    ) and label == "Feature validation (dry run)"


def test_a_slow_feature_keeps_reporting_that_it_is_working_company_by_company(world):
    conn, ids, fid = world
    seen = []
    validate(conn, fid, report=lambda phase, msg: seen.append(msg))
    first = [m for m in seen if m.startswith("first read: company")]
    second = [m for m in seen if m.startswith("second read: company")]
    assert first == ["first read: company 1 of 2"] and second == [
        "second read: company 1 of 2"
    ]  # reported at the first company, then every 200
