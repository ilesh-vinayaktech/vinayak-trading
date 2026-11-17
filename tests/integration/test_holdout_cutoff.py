from datetime import UTC, date, datetime

import psycopg
import pytest
from psycopg.types.json import Jsonb

from algo.backtest.validation import registry
from algo.data.store.migrate import migrate
from algo.promotion import verdicts as pv
from algo.research import holdout_batch as hb
from algo.research import holdout_cutoff as co
from algo.research import holdout_lock
from algo.research.holdout_lock import Lock
from tests.support.research_lock import write_lock_file

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 17, 6, 0, tzinfo=UTC)
LOCK = Lock(date(2024, 12, 31), date(2025, 1, 1), date(2026, 11, 13))


def add_definition(conn, sid, **kw):
    conn.execute(
        "SET session_replication_role = replica"
    )  # the rows' foreign parents are not what is tested here
    try:
        return _add_definition(conn, sid, **kw)
    finally:
        conn.execute("SET session_replication_role = DEFAULT")


def _add_definition(
    conn, sid, *, passed=True, verdict_status="DONE", with_study=True, ver=1, dirty=False
):
    conn.execute(
        "INSERT INTO strategy_definition (strategy_id, version, reason, definition, definition_sha256, created_by, created_at)"
        " VALUES (%s,%s,'t','{}',%s,'t',%s)",
        (sid, ver, f"{sid:0<64}"[:64].replace("_", "a").lower(), NOW),
    )
    if not with_study:
        return None
    spec = {
        "definition": {"strategy_id": sid, "version": ver},
        "fixed": {"exit_share": 50, "max_positions": 20},
        "name": sid,
    }
    exp = conn.execute(
        "INSERT INTO experiment (name, strategy_id, hypothesis, style, param_ranges, holdout_start, holdout_end, registered_at, study, study_sha256, family_id)"
        " VALUES (%s,'dsl','h','long_only','{}','2023-01-01','2024-12-31',%s,%s,%s,1) RETURNING experiment_id",
        (
            f"{sid} fixed",
            NOW,
            Jsonb({"spec": spec, "code": {"commit": "abc", "dirty": dirty}}),
            f"sha-{sid}",
        ),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO study_dataset (experiment_id, dataset_sha256, manifest, sealed_at) VALUES (%s,%s,'{}',%s)",
        (exp, f"d{exp}", NOW),
    )
    run = conn.execute(
        "INSERT INTO study_run (experiment_id, kind, status, requested_by, created_at) VALUES (%s,'verdict',%s,%s,%s) RETURNING run_id",
        (exp, verdict_status, "00000000-0000-0000-0000-000000000001", NOW),
    ).fetchone()[0]
    if verdict_status == "DONE":
        conn.execute(
            "INSERT INTO validation_report (experiment_id, run_id, passed, thresholds_status, n_trials, evidence, gates, created_at, refs)"
            " VALUES (%s,%s,%s,'confirmed',3,'{}','[]',%s,%s)",
            (exp, run, passed, NOW, Jsonb({"chosen": {"exit_share": 50, "max_positions": 20}})),
        )
    return exp


@pytest.fixture
def env(conn, monkeypatch, tmp_path):
    migrate(conn)
    monkeypatch.setattr(holdout_lock, "LOCK_FILE", write_lock_file(tmp_path / "lock.json", LOCK))
    holdout_lock.anchor(conn, LOCK, by="owner", reason="test", now=NOW)
    monkeypatch.setattr(registry, "family_trial_count", lambda c, f: 100)
    return conn


def population(conn, names=("A", "B", "C", "D")):
    return {n: add_definition(conn, n) for n in names}


def test_the_cutoff_waits_for_the_last_study_then_fires_once_and_cannot_be_changed(env):
    exp = add_definition(env, "A")
    add_definition(env, "B", verdict_status="RUNNING")
    assert co.round_complete(env) is False and co.fire_batch1(env, NOW) is None
    env.execute(
        "UPDATE study_run SET status='CANCELLED' WHERE experiment_id = (SELECT experiment_id FROM experiment WHERE name='B fixed')"
    )
    assert (
        co.round_complete(env) is True
    )  # a study that ended without a verdict is terminal, simply not a member
    cid = co.fire_batch1(env, NOW)
    assert cid and co.fire_batch1(env, NOW) is None  # fires once
    snap = env.execute("SELECT snapshot FROM holdout_cutoff").fetchone()[0]["candidates"]
    assert {c["candidate_id"]: c["development_verdict"] for c in snap} == {
        "A@1": "PASSED",
        "B@1": "NO_VERDICT",
    }
    assert snap[0]["experiment_id"] == exp
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        env.execute("UPDATE holdout_cutoff SET fired_at = fired_at")
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        env.execute("DELETE FROM holdout_cutoff")


def test_a_definition_without_a_study_keeps_the_round_open(env):
    add_definition(env, "A")
    add_definition(env, "B", with_study=False)
    assert co.fire_batch1(env, NOW) is None


def test_nothing_is_frozen_before_the_audit_is_signed_and_membership_is_mechanical_after(env):
    population(env)
    add_definition(env, "E", passed=False)
    cid = co.fire_batch1(env, NOW)
    for n in "ABCD":
        co.record_provenance(env, f"{n}@1", "ELIGIBLE", "mechanical origin shown", NOW)
    p = co.plan(env, cid)
    assert (
        not p.can_freeze
        and any("not signed" in x for x in p.problems)
        and co.freeze_batch(env, cid, "owner", NOW) is None
    )
    assert env.execute("SELECT count(*) FROM holdout_batch").fetchone()[0] == 0
    co.sign_audit(env, "owner", "audit text", NOW)
    p = co.plan(env, cid)
    assert p.can_freeze and p.members == (
        "A@1",
        "B@1",
        "C@1",
        "D@1",
    )  # E failed development, so it is not a member; nobody picks among the rest
    bid = co.freeze_batch(env, cid, "owner", NOW)
    assert hb.slots(env) == (0, 4, 26)
    assert (
        env.execute("SELECT state FROM holdout_batch WHERE batch_id=%s", (bid,)).fetchone()[0]
        == "FROZEN"
    )


def test_an_ineligible_candidate_is_excluded_with_reason_3_and_never_frozen(env):
    population(env, ("A", "B", "C", "D"))
    cid = co.fire_batch1(env, NOW)
    for n in "ABC":
        co.record_provenance(env, f"{n}@1", "ELIGIBLE", "x", NOW)
    co.record_provenance(
        env, "D@1", "INELIGIBLE", "chosen by hand after holdout-period decisions were drawn", NOW
    )
    co.sign_audit(env, "owner", "audit", NOW)
    p = co.plan(env, cid)
    assert p.members == ("A@1", "B@1", "C@1") and list(p.excluded) == ["D@1"]
    co.freeze_batch(env, cid, "owner", NOW)
    assert env.execute("SELECT candidate_id, reason FROM holdout_exclusion").fetchall() == [
        ("D@1", 3)
    ]
    assert sorted(
        r[0] for r in env.execute("SELECT candidate_id FROM holdout_candidate").fetchall()
    ) == [f"study-{i}" for i in sorted(p.experiments.values())]


def test_unresolved_provenance_blocks_the_freeze_and_the_audit_cannot_add_a_member(env):
    population(env, ("A", "B", "C"))
    cid = co.fire_batch1(env, NOW)
    co.sign_audit(env, "owner", "audit", NOW)
    for n in "AB":
        co.record_provenance(env, f"{n}@1", "ELIGIBLE", "x", NOW)
    p = co.plan(env, cid)
    assert not p.can_freeze and any("not resolved for C@1" in x for x in p.problems)
    add_definition(
        env, "Z"
    )  # registered after the snapshot: it is not in it, whatever its provenance
    co.record_provenance(env, "Z@1", "ELIGIBLE", "x", NOW)
    assert "Z@1" not in co.plan(env, cid).members


def test_a_single_candidate_can_be_frozen_but_more_than_the_slots_left_cannot(env):
    population(env, ("A", "B"))
    cid = co.fire_batch1(env, NOW)
    for n in "AB":
        co.record_provenance(env, f"{n}@1", "ELIGIBLE", "x", NOW)
    co.sign_audit(env, "owner", "audit", NOW)
    env.execute(
        "INSERT INTO holdout_batch (state, lock_id, evaluator_version, registered_by, registered_at) SELECT 'REGISTERED', lock_id, %s, 'o', %s FROM research_lock LIMIT 1",
        (hb.EVALUATOR_VERSION, NOW),
    )
    bid = env.execute("SELECT batch_id FROM holdout_batch").fetchone()[0]
    for i in range(29):  # one slot left
        env.execute(
            "INSERT INTO holdout_candidate (batch_id, candidate_id, state, seed, reserved_at) VALUES (%s,%s,'RESERVED',%s,%s)",
            (bid, f"x{i}", f"{i:032x}", NOW),
        )
    p = co.plan(env, cid)
    assert not p.can_freeze and any("do not fit the 1 slots left" in x for x in p.problems)
    single = co.fire_on_demand(env, ["A@1"], NOW)
    assert co.plan(env, single).can_freeze and co.freeze_batch(env, single, "owner", NOW)
    assert hb.slots(env) == (0, 30, 0)


def test_a_candidate_of_the_snapshot_that_already_holds_a_slot_is_not_a_member_again(env):
    population(env, ("A", "B", "C"))
    cid = co.fire_batch1(env, NOW)
    for n in "ABC":
        co.record_provenance(env, f"{n}@1", "ELIGIBLE", "x", NOW)
    co.sign_audit(env, "owner", "audit", NOW)
    assert co.freeze_batch(env, cid, "owner", NOW)
    again = co.fire_on_demand(env, ["A@1", "B@1", "C@1"], NOW)
    assert co.plan(env, again).members == ()
    assert pv  # the verdict reader is not involved: a cutoff reads development verdicts only


def test_a_member_is_evaluated_through_its_newest_clean_passed_study_and_without_one_the_batch_waits(
    env,
):
    population(env, ("A", "B", "C"))
    cid = co.fire_batch1(env, NOW)
    for n in "ABC":
        co.record_provenance(env, f"{n}@1", "ELIGIBLE", "x", NOW)
    co.sign_audit(env, "owner", "audit", NOW)
    dirty = env.execute("SELECT experiment_id FROM experiment WHERE name='A fixed'").fetchone()[0]
    env.execute("SET session_replication_role = replica")
    env.execute(
        "UPDATE experiment SET study = jsonb_set(study, '{code,dirty}', 'true') WHERE experiment_id=%s",
        (dirty,),
    )
    env.execute("SET session_replication_role = DEFAULT")
    p = co.plan(env, cid)
    assert (
        not p.can_freeze
        and "A@1" not in p.members
        and any("clean-code study" in x and "A@1" in x for x in p.problems)
    )
    env.execute("SET session_replication_role = replica")
    env.execute(
        "INSERT INTO experiment (name, strategy_id, hypothesis, style, param_ranges, holdout_start, holdout_end, registered_at, study, study_sha256, family_id)"
        " SELECT 'A fixed clean', strategy_id, hypothesis, style, param_ranges, holdout_start, holdout_end, registered_at, jsonb_set(study, '{code,dirty}', 'false'), 'sha-A-clean', family_id FROM experiment WHERE experiment_id=%s",
        (dirty,),
    )
    new = env.execute("SELECT experiment_id FROM experiment WHERE name='A fixed clean'").fetchone()[
        0
    ]
    env.execute(
        "INSERT INTO study_run (experiment_id, kind, status, requested_by, created_at) VALUES (%s,'verdict','DONE','00000000-0000-0000-0000-000000000001',%s) RETURNING run_id",
        (new, NOW),
    )
    run = env.execute("SELECT max(run_id) FROM study_run").fetchone()[0]
    env.execute(
        "INSERT INTO validation_report (experiment_id, run_id, passed, thresholds_status, n_trials, evidence, gates, created_at, refs) VALUES (%s,%s,true,'confirmed',3,'{}','[]',%s,%s)",
        (new, run, NOW, Jsonb({"chosen": {"exit_share": 50, "max_positions": 20}})),
    )
    env.execute("SET session_replication_role = DEFAULT")
    p = co.plan(env, cid)
    assert p.members == ("A@1", "B@1", "C@1") and p.experiments["A@1"] == new


def test_submit_puts_a_new_strategy_through_the_holdout_at_any_time_on_the_owners_declaration(env):
    population(env, ("A", "B"))
    co.sign_audit(env, "owner", "audit", NOW)
    with pytest.raises(co.CutoffError, match="not built from 2025-2026"):
        co.submit(env, ["A@1"], "  ", "owner", NOW)
    batch = co.submit(
        env, ["A@1"], "the idea came from a paper, not from any 2025-2026 result", "owner", NOW
    )  # a batch of one, no calendar date
    assert (
        env.execute("SELECT state FROM holdout_batch WHERE batch_id=%s", (batch,)).fetchone()[0]
        == "FROZEN"
    )
    assert hb.slots(env) == (0, 1, 29)
    assert (
        env.execute(
            "SELECT status, reason FROM holdout_provenance WHERE candidate_id='A@1'"
        ).fetchone()[0]
        == "ELIGIBLE"
    )
    second = co.submit(env, ["B@1"], "declared", "owner", NOW)  # later, on its own
    assert second != batch and hb.slots(env) == (0, 2, 28)
    assert (
        env.execute("SELECT count(*) FROM holdout_cutoff WHERE kind='ON_DEMAND'").fetchone()[0] == 2
    )
    with pytest.raises(co.CutoffError, match="cannot freeze"):
        co.submit(
            env, ["A@1"], "again", "owner", NOW
        )  # a candidate already holding a slot is never tested twice


def test_submit_refuses_a_strategy_without_a_clean_passed_study_and_an_unknown_one(env):
    add_definition(env, "D", dirty=True)
    add_definition(env, "E", passed=False)
    for cid in ("D@1", "E@1"):
        with pytest.raises(
            co.CutoffError, match="no study registered from a clean commit has passed"
        ):
            co.submit(env, [cid], "declared", "owner", NOW)
    with pytest.raises(co.CutoffError, match="unknown definition"):
        co.fire_on_demand(env, ["NOPE@1"], NOW)
