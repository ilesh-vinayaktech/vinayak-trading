# ruff: noqa: F811
from datetime import UTC, date, datetime

import psycopg
import pytest
from psycopg.types.json import Jsonb

from algo.research import holdout_locks as hl
from tests.integration.test_holdout_cutoff import NOW, add_definition, env  # noqa: F401  (env is a fixture)

pytestmark = pytest.mark.integration
EARLY = datetime(2026, 11, 1, tzinfo=UTC)


def test_the_lock_is_the_latest_of_definition_study_and_code_and_the_forward_start_is_the_next_session(
    env,
):  # noqa: F811
    add_definition(env, "A")
    rec = hl.compute(env, "A@1", lambda c: EARLY)
    assert (
        rec["strategy_locked_at"] == NOW
    )  # the study (and the definition) are registered 2026-11-17 06:00 UTC, after the commit
    assert rec["forward_evaluation_start"] == date(
        2026, 11, 18
    )  # the 17th opened at 09:15 IST, before the lock
    later = datetime(2026, 11, 19, 9, tzinfo=UTC)  # a code commit after the study moves the lock
    assert hl.compute(env, "A@1", lambda c: later)["strategy_locked_at"] == later
    assert hl.compute(env, "A@1", lambda c: later)["forward_evaluation_start"] == date(2026, 11, 20)
    assert rec["components"]["not_pinned"] and rec["code_commit"] == "abc"


def test_a_lock_after_the_close_or_on_a_weekend_starts_at_the_next_open_session(env, monkeypatch):  # noqa: F811
    add_definition(env, "A")
    friday_evening = datetime(2026, 11, 20, 12, tzinfo=UTC)  # 17:30 IST, after the close
    assert hl.compute(env, "A@1", lambda c: friday_evening)["forward_evaluation_start"] == date(
        2026, 11, 23
    )  # Monday
    assert hl.first_session_after(env, datetime(2026, 11, 13, 2, tzinfo=UTC)) == date(
        2026, 11, 16
    )  # never from the holdout days themselves


def test_a_lock_that_cannot_be_established_is_refused_not_guessed(env):  # noqa: F811
    add_definition(env, "A")
    with pytest.raises(hl.LockError, match="cannot be established"):
        hl.compute(env, "A@1", lambda c: None)
    add_definition(env, "B", with_study=False)
    with pytest.raises(hl.LockError, match="no definition or no fixed-setting study"):
        hl.compute(env, "B@1", lambda c: EARLY)
    add_definition(env, "C", dirty=True)
    with pytest.raises(hl.LockError, match="differs from its commit"):
        hl.compute(env, "C@1", lambda c: EARLY)
    ok, refused = hl.compute_all(env, lambda c: EARLY)
    assert [r["candidate_id"] for r in ok] == ["A@1"] and set(refused) == {"B@1", "C@1"}


def test_a_recorded_lock_is_permanent_and_cannot_start_inside_the_holdout(env):  # noqa: F811
    add_definition(env, "A")
    rec = hl.compute(env, "A@1", lambda c: EARLY)
    hl.record(env, rec, NOW)
    assert env.execute("SELECT forward_evaluation_start FROM strategy_lock").fetchone()[0] == date(
        2026, 11, 18
    )
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        env.execute("UPDATE strategy_lock SET code_commit='x'")
    with pytest.raises(psycopg.errors.UniqueViolation):
        hl.record(env, rec, NOW)
    with pytest.raises(psycopg.errors.CheckViolation):
        env.execute(
            "INSERT INTO strategy_lock VALUES ('Z@1', %s, '2026-11-13', 'h', 'c', %s, %s)",
            (NOW, Jsonb({}), NOW),
        )
