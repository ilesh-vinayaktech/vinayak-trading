import threading
from datetime import UTC, date, datetime

import psycopg
import pytest
from psycopg.types.json import Jsonb

from algo.data.store.migrate import migrate
from algo.research import holdout_batch as hb
from algo.research import holdout_lock
from algo.research.holdout_lock import Lock
from tests.support.research_lock import write_lock_file

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 15, 6, 0, tzinfo=UTC)
LOCK = Lock(date(2024, 12, 31), date(2025, 1, 1), date(2026, 11, 13))


@pytest.fixture
def env(conn, monkeypatch, tmp_path):
    """Migrated database with the real window anchored, and three development validation reports (two passed, one failed)."""
    migrate(conn)
    monkeypatch.setattr(holdout_lock, "LOCK_FILE", write_lock_file(tmp_path / "lock.json", LOCK))
    holdout_lock.anchor(conn, LOCK, by="owner", reason="test", now=NOW)
    conn.execute(
        "SET session_replication_role = replica"
    )  # the reports' experiment and run rows are not what is tested here
    for rid, passed in ((1, True), (2, True), (3, False)):
        conn.execute(
            "INSERT INTO validation_report (report_id, experiment_id, run_id, passed, thresholds_status, n_trials, evidence, gates, created_at)"
            " VALUES (%s, %s, %s, %s, 'confirmed', 3, '{}', '[]', %s)",
            (rid, rid, rid, passed, NOW),
        )
    for i in (
        1,
        2,
        3,
    ):  # the studies behind the candidates; study 3 was registered from a dirty tree
        conn.execute(
            "INSERT INTO experiment (experiment_id, name, strategy_id, hypothesis, style, param_ranges, holdout_start, holdout_end, registered_at, study, study_sha256)"
            " VALUES (%s, %s, 'trend_pullback', 'h', 'long_only', '{}', '2024-01-01', '2024-12-31', %s, %s, %s)",
            (i, f"study {i}", NOW, Jsonb({"code": {"commit": "abc", "dirty": i == 3}}), f"s{i}"),
        )
        conn.execute(
            "INSERT INTO study_dataset (experiment_id, dataset_sha256, manifest, sealed_at) VALUES (%s,%s,'{}',%s)",
            (i, f"d{i}", NOW),
        )
    conn.execute("SET session_replication_role = DEFAULT")
    return conn


def cand(i, report=None, family="momentum"):
    return hb.Candidate(f"c{i}", family, "1", f"p{i}", f"d{i}", f"s{i}", report or i)


def manifest(batch_id, candidates=None):
    return hb.Manifest(
        batch_id, tuple(candidates or (cand(1), cand(2))), {"momentum": 30}, LOCK.holdout_start, LOCK.holdout_end,
        "holm", "1", hb.EVALUATOR_VERSION,
    )  # fmt: skip


def frozen(conn):
    bid = hb.register(conn, by="owner", now=NOW)
    hb.freeze(conn, bid, manifest(bid), NOW)
    return bid


def all_pass(cap, m):
    return hb.Results(
        {(c.candidate_id, "oos_sharpe"): "PASS" for c in m.candidates}, {"detail": "owner only"}
    )


def reader():
    return object()


def test_only_one_batch_can_ever_be_registered(env):
    hb.register(env, by="owner", now=NOW)
    with pytest.raises(hb.BatchError, match="already exists"):
        hb.register(env, by="owner", now=NOW)


def test_two_processes_registering_at_once_leave_exactly_one_batch(env, pg_url):
    results = []

    def go():
        with psycopg.connect(pg_url, autocommit=True) as c:
            try:
                hb.register(c, by="owner", now=NOW)
                results.append("ok")
            except hb.BatchError:
                results.append("refused")

    threads = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["ok", "refused"]
    assert env.execute("SELECT count(*) FROM holdout_batch").fetchone()[0] == 1


def test_freezing_checks_the_manifest_and_the_development_evidence_before_anything(env):
    bid = hb.register(env, by="owner", now=NOW)
    with pytest.raises(hb.BatchError, match="no passed development validation report"):
        hb.freeze(env, bid, manifest(bid, [cand(1), cand(3)]), NOW)  # report 3 failed
    with pytest.raises(hb.BatchError, match="no passed development validation report"):
        hb.freeze(env, bid, manifest(bid, [cand(1, report=99)]), NOW)  # no such report
    with pytest.raises(hb.BatchError, match="must equal the global holdout"):
        hb.freeze(
            env,
            bid,
            hb.Manifest(
                bid,
                (cand(1),),
                {"momentum": 30},
                date(2025, 1, 2),
                LOCK.holdout_end,
                "holm",
                "1",
                hb.EVALUATOR_VERSION,
            ),
            NOW,
        )
    assert env.execute("SELECT state FROM holdout_batch").fetchone()[0] == "REGISTERED"
    sha = hb.freeze(env, bid, manifest(bid), NOW)
    assert env.execute("SELECT state, manifest_sha256 FROM holdout_batch").fetchone() == (
        "FROZEN",
        sha,
    )


def test_a_frozen_manifest_and_the_state_order_cannot_be_changed_by_anyone(env):
    bid = frozen(env)
    for sql in (
        "UPDATE holdout_batch SET manifest = '{}'::jsonb",
        "UPDATE holdout_batch SET manifest_sha256 = 'x'",
        "UPDATE holdout_batch SET state = 'REGISTERED'",
        "UPDATE holdout_batch SET state = 'CONSUMED'",  # skipping EVALUATING
        "UPDATE holdout_batch SET lock_id = 99",
        "DELETE FROM holdout_batch",
    ):
        with pytest.raises(psycopg.errors.RaiseException):
            env.execute(sql)
    assert (
        env.execute("SELECT state FROM holdout_batch WHERE batch_id=%s", (bid,)).fetchone()[0]
        == "FROZEN"
    )


def test_an_unfrozen_batch_cannot_be_evaluated_and_a_forged_capability_is_refused(env):
    bid = hb.register(env, by="owner", now=NOW)
    with pytest.raises(hb.BatchError, match="REGISTERED"):
        hb.evaluate(env, bid, all_pass, reader, NOW)


def test_a_clean_evaluation_commits_redacted_verdicts_once_and_consumes_the_holdout(env):
    bid = frozen(env)
    seen = {}

    def run(cap, m):
        seen["state_during"] = env.execute("SELECT state FROM holdout_batch").fetchone()[0]
        seen["reader"] = cap.reader
        seen["cap"] = cap
        return all_pass(cap, m)

    token = object()
    hb.evaluate(env, bid, run, lambda: token, NOW)
    assert (
        seen["state_during"] == "EVALUATING" and seen["reader"] is token
    )  # consumed BEFORE the data was read
    with pytest.raises(hb.BatchError, match="revoked"):
        _ = seen["cap"].reader
    assert env.execute("SELECT state FROM holdout_batch").fetchone()[0] == "CONSUMED"
    assert sorted(hb.read_verdicts(env)) == [
        ("c1", "oos_sharpe", "PASS"),
        ("c2", "oos_sharpe", "PASS"),
    ]
    assert env.execute("SELECT report FROM holdout_report").fetchone()[0] == {
        "detail": "owner only"
    }
    with pytest.raises(hb.BatchError, match="CONSUMED"):
        hb.evaluate(env, bid, all_pass, reader, NOW)  # never twice
    with pytest.raises(psycopg.errors.RaiseException):
        env.execute("DELETE FROM holdout_verdict")


def test_verdicts_are_unreadable_until_the_batch_is_consumed_and_only_clean_candidates_are_promotable(
    env,
):
    bid = frozen(env)
    with pytest.raises(hb.BatchError, match="no consumed"):
        hb.read_verdicts(env)

    def run(cap, m):
        return hb.Results(
            {("c1", "oos_sharpe"): "PASS", ("c1", "regimes"): "NOT_APPLICABLE", ("c2", "oos_sharpe"): "PASS", ("c2", "deflated_sharpe"): "INSUFFICIENT_EVIDENCE"},
            {},
        )  # fmt: skip

    hb.evaluate(env, bid, run, reader, NOW)
    assert hb.promotable(env, "c1") is True
    assert hb.promotable(env, "c2") is False  # insufficient evidence is never a weak pass
    assert hb.promotable(env, "nobody") is False


def test_a_crash_leaves_the_batch_evaluating_with_nothing_exposed_and_only_the_same_manifest_resumes(
    env,
):
    bid = frozen(env)

    def crash(cap, m):
        raise RuntimeError("the evaluator died after reading some holdout data")

    with pytest.raises(RuntimeError):
        hb.evaluate(env, bid, crash, reader, NOW)
    assert env.execute("SELECT state FROM holdout_batch").fetchone()[0] == "EVALUATING"
    assert env.execute("SELECT count(*) FROM holdout_verdict").fetchone()[0] == 0
    with pytest.raises(hb.BatchError, match="no consumed"):
        hb.read_verdicts(env)
    with pytest.raises(
        hb.BatchError, match="register"
    ):  # a second batch is impossible while this one is unresolved
        hb.register(env, by="owner", now=NOW)
    hb.evaluate(env, bid, all_pass, reader, NOW)  # recovery: same manifest, same evaluator version
    assert env.execute("SELECT state FROM holdout_batch").fetchone()[0] == "CONSUMED"


def test_a_resume_with_a_different_evaluator_version_or_a_tampered_manifest_is_refused(
    env, monkeypatch
):
    bid = frozen(env)
    with pytest.raises(RuntimeError):
        hb.evaluate(env, bid, lambda c, m: (_ for _ in ()).throw(RuntimeError("died")), reader, NOW)
    monkeypatch.setattr(hb, "EVALUATOR_VERSION", "holdout-evaluator-2")
    with pytest.raises(hb.BatchError, match="evaluator version"):
        hb.evaluate(env, bid, all_pass, reader, NOW)
    monkeypatch.undo()
    env.execute(
        "ALTER TABLE holdout_batch DISABLE TRIGGER holdout_batch_forward_only"
    )  # simulate someone editing the manifest underneath
    env.execute(
        "UPDATE holdout_batch SET manifest = jsonb_set(manifest, '{correction_method}', '\"none\"')"
    )
    with pytest.raises(hb.BatchError, match="manifest"):
        hb.evaluate(env, bid, all_pass, reader, NOW)


def test_results_that_do_not_cover_the_manifest_leave_the_batch_unresolved_not_consumed_with_gaps(
    env,
):
    bid = frozen(env)
    with pytest.raises(hb.BatchError, match="no verdict for candidate c2"):
        hb.evaluate(env, bid, lambda c, m: hb.Results({("c1", "g"): "PASS"}, {}), reader, NOW)
    assert env.execute("SELECT state FROM holdout_batch").fetchone()[0] == "EVALUATING"
    assert env.execute("SELECT count(*) FROM holdout_verdict").fetchone()[0] == 0


def test_when_recovery_is_impossible_the_batch_is_marked_failed_and_the_holdout_stays_consumed(env):
    bid = frozen(env)
    with pytest.raises(hb.BatchError, match="not being evaluated"):
        hb.fail(env, bid, "nothing to fail", NOW)  # only an EVALUATING batch can fail
    with pytest.raises(RuntimeError):
        hb.evaluate(env, bid, lambda c, m: (_ for _ in ()).throw(RuntimeError("died")), reader, NOW)
    hb.fail(env, bid, "the data snapshot can no longer be reproduced", NOW)
    assert env.execute("SELECT state, failure FROM holdout_batch").fetchone() == (
        "EVALUATION_FAILED",
        "the data snapshot can no longer be reproduced",
    )
    with pytest.raises(hb.BatchError, match="EVALUATION_FAILED"):
        hb.evaluate(env, bid, all_pass, reader, NOW)
    with pytest.raises(hb.BatchError, match="already exists"):
        hb.register(env, by="owner", now=NOW)


def test_the_research_window_cannot_change_once_a_batch_exists(env):
    hb.register(env, by="owner", now=NOW)
    with pytest.raises(
        psycopg.errors.RaiseException, match="cannot change once a holdout batch exists"
    ):
        holdout_lock.anchor(
            env,
            Lock(date(2025, 6, 30), date(2025, 7, 1), date(2026, 11, 13)),
            by="x",
            reason="y",
            now=NOW,
        )


def test_a_manifest_cannot_be_set_twice_and_an_unknown_batch_is_refused(env):
    bid = frozen(env)
    with pytest.raises(hb.BatchError, match="not REGISTERED"):
        hb.freeze(env, bid, manifest(bid), NOW)
    with pytest.raises(hb.BatchError, match="no holdout batch 99"):
        hb.evaluate(env, 99, all_pass, reader, NOW)


def test_a_candidate_must_be_a_real_clean_study_whose_dataset_hash_matches_what_it_sealed(env):
    bid = hb.register(env, by="owner", now=NOW)
    ghost = hb.Candidate("ghost", "momentum", "1", "pg", "dg", "no-such-study", 1)
    wrong_data = hb.Candidate("c1", "momentum", "1", "p1", "not-its-dataset", "s1", 1)
    wrong_report = hb.Candidate(
        "c1", "momentum", "1", "p1", "d1", "s1", 2
    )  # report 2 belongs to study 2
    for bad, text in (
        (ghost, "no registered study has study_sha256"),
        (wrong_data, "does not match the dataset its study sealed"),
        (wrong_report, "for its study"),
    ):
        with pytest.raises(hb.BatchError, match=text):
            hb.freeze(env, bid, manifest(bid, [bad]), NOW)
    dirty = hb.Candidate(
        "c3", "momentum", "1", "p3", "d3", "s3", 3
    )  # passed validation, but its study came from a dirty tree
    with pytest.raises(hb.BatchError, match="cannot be reproduced"):
        hb.freeze(env, bid, manifest(bid, [dirty]), NOW)
    hb.freeze(env, bid, manifest(bid, [cand(1), cand(2)]), NOW)
