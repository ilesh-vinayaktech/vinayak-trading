from datetime import UTC, datetime

import psycopg
import pytest

from algo.backtest.validation import registry
from algo.data.store import migrate as migrate_mod
from algo.data.store.migrate import migrate
from algo.research.study import StudyError

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
HYP = "Buying a 5-day RSI dip inside a 200-day uptrend beats buy-and-hold after costs."
WHY = (
    "A different mechanism from every existing family: it trades cross-sectional value, not trend."
)


def experiment(conn, name, family_id=None):
    return registry.register(
        conn, name=name, strategy_id="s", hypothesis=HYP, style="long_only", param_ranges={"a": [1, 100]},
        holdout=(NOW.date(), NOW.date()), now=NOW, family_id=family_id,
    )  # fmt: skip


def test_the_migration_gives_every_earlier_experiment_one_shared_family(conn):
    files = sorted(migrate_mod.MIGRATIONS.glob("*.sql"))
    before = [f for f in files if f.name < "068"]
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migration (name TEXT PRIMARY KEY)")
    for f in before:  # the database as it was before families
        conn.execute(f.read_text())
        conn.execute("INSERT INTO schema_migration VALUES (%s)", (f.name,))
    ids = []
    for name in (
        "old one",
        "old two",
    ):  # the schema before families has no family column: plain SQL
        row = conn.execute(
            "INSERT INTO experiment (name, strategy_id, hypothesis, style, param_ranges, holdout_start, holdout_end, registered_at)"
            " VALUES (%s, 's', %s, 'long_only', '{}', %s, %s, %s) RETURNING experiment_id",
            (name, HYP, NOW.date(), NOW.date(), NOW),
        ).fetchone()
        ids.append(row[0])
    for i, eid in enumerate(ids):
        conn.execute(
            "INSERT INTO experiment_trial (experiment_id, params, params_hash, sharpe, recorded_at) VALUES (%s, '{}', %s, 0.1, %s)",
            (eid, f"h{i}", NOW),
        )
    assert migrate(conn) == [f.name for f in files if f.name >= "068"]
    fam = conn.execute("SELECT family_id FROM research_family").fetchall()
    assert len(fam) == 1
    got = conn.execute("SELECT family_id FROM experiment ORDER BY experiment_id").fetchall()
    assert got == [(fam[0][0],), (fam[0][0],)]
    assert registry.family_trial_count(conn, fam[0][0]) == 2  # nothing was lost


@pytest.fixture
def env(conn):
    from tests.support.research_lock import anchor_open_lock

    migrate(conn)
    anchor_open_lock(conn)
    return conn


def test_a_new_family_needs_a_name_a_hypothesis_and_a_real_justification(env):
    fid = registry.create_family(
        env, name="Value", hypothesis=HYP, justification=WHY, created_by=None, now=NOW
    )
    assert fid > 1
    with pytest.raises(registry.RegistryError, match="already"):
        registry.create_family(
            env, name="Value", hypothesis=HYP, justification=WHY, created_by=None, now=NOW
        )
    with pytest.raises(registry.RegistryError, match="needs a name"):
        registry.create_family(
            env, name="   ", hypothesis=HYP, justification=WHY, created_by=None, now=NOW
        )
    with pytest.raises(registry.RegistryError, match="justification"):
        registry.create_family(
            env, name="Other", hypothesis=HYP, justification="too short", created_by=None, now=NOW
        )
    with pytest.raises(registry.RegistryError, match="hypothesis"):
        registry.create_family(
            env, name="Other", hypothesis="short", justification=WHY, created_by=None, now=NOW
        )
    names = [f["name"] for f in registry.list_families(env)]
    assert "Value" in names and len(names) == 2


def test_a_family_and_an_experiments_family_can_never_change(env):
    fid = registry.create_family(
        env, name="Value", hypothesis=HYP, justification=WHY, created_by=None, now=NOW
    )
    e = experiment(env, "x", fid)
    for sql in ("UPDATE research_family SET name='z'", "DELETE FROM research_family"):
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            env.execute(sql)
    with pytest.raises(psycopg.errors.RaiseException, match="locked"):
        env.execute("UPDATE experiment SET family_id = 1 WHERE experiment_id = %s", (e,))


def test_trials_count_across_the_whole_family_and_a_re_registration_does_not_reset_them(env):
    fid = registry.create_family(
        env, name="Value", hypothesis=HYP, justification=WHY, created_by=None, now=NOW
    )
    other = registry.create_family(
        env, name="Quality", hypothesis=HYP, justification=WHY + " Again.", created_by=None, now=NOW
    )
    first = experiment(env, "first", fid)
    for i, s in enumerate((0.1, 0.2, 0.3)):
        registry.record_trial(env, first, {"a": i + 1}, s, None, NOW)
    again = experiment(env, "the same idea registered again", fid)  # a re-registration: same family
    registry.record_trial(env, again, {"a": 1}, 0.4, None, NOW)
    elsewhere = experiment(env, "unrelated", other)
    registry.record_trial(env, elsewhere, {"a": 9}, 0.9, None, NOW)
    assert registry.trial_count(env, again) == 1  # the study's own count
    assert registry.family_trial_count(env, fid) == 4  # the family's: nothing reset
    assert registry.family_trial_sharpes(env, fid) == [0.1, 0.2, 0.3, 0.4]
    assert registry.family_trial_count(env, other) == 1  # another family is not mixed in


def test_the_study_store_refuses_a_study_without_a_real_family(env):
    from algo.research.study_store import register_study
    from tests.unit.research.test_study import spec

    with pytest.raises(StudyError, match="research family"):
        register_study(env, None, spec(family_id=None), NOW)
    with pytest.raises(StudyError, match="no research family 9999"):
        register_study(env, None, spec(family_id=9999), NOW)


def test_an_experiment_outside_any_family_deflates_over_its_own_trials_only(env):
    solo = experiment(env, "no family")  # family_id left empty
    registry.record_trial(env, solo, {"a": 1}, 0.5, None, NOW)
    assert registry.deflation_trials(env, solo) == (1, [0.5])
    assert (
        registry.experiment_family(env, solo) is None
        and registry.experiment_family(env, 9999) is None
    )
