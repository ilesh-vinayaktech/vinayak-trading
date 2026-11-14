from datetime import timedelta
from decimal import Decimal as D

import psycopg
import pytest

from algo.backtest.validation import registry
from algo.research import dataset, holdout_lock, study_runner
from algo.research.holdout_lock import ResearchReader
from algo.research.study_runner import StudyRunError
from algo.research.study_store import register_study
from tests.integration.test_study_runner import DAYS, NOW, build_env, small_spec

pytestmark = pytest.mark.integration


@pytest.fixture
def env(conn):
    return build_env(conn, DAYS)


def study_doc(conn, sid):
    return conn.execute(
        "SELECT study, study_sha256 FROM experiment WHERE experiment_id=%s", (sid,)
    ).fetchone()


def test_registration_pins_the_moment_and_the_code_inside_the_locked_study(env):
    conn, owner = env
    sid = register_study(conn, owner, small_spec(), NOW)
    doc, sha = study_doc(conn, sid)
    assert doc["known_at"] == NOW.isoformat()
    assert (
        set(doc["code"]) == {"commit", "dirty", "strategy_sha256"}
        and len(doc["code"]["strategy_sha256"]) == 64
    )
    assert isinstance(doc["code"]["dirty"], bool)
    assert sha == registry.params_hash(doc)  # the whole study hash covers the pins


def test_the_first_run_seals_the_dataset_and_a_second_run_reproduces_it_exactly(env):
    conn, owner = env
    sid = register_study(conn, owner, small_spec(), NOW)
    assert dataset.sealed(conn, sid) is None
    study_runner.prepare(conn, small_spec(), sid)
    sealed = dataset.sealed(conn, sid)
    assert sealed and len(sealed) == 64
    manifest = conn.execute(
        "SELECT manifest FROM study_dataset WHERE experiment_id=%s", (sid,)
    ).fetchone()[0]
    assert set(manifest) >= {
        "known_at",
        "freeze",
        "data_hash",
        "universe",
        "window",
        "cost_schedules",
        "price_source",
    }
    assert manifest["known_at"] == NOW.isoformat() and manifest["universe"]["instruments"] == 8
    study_runner.prepare(conn, small_spec(), sid)  # identical data: passes and changes nothing
    assert dataset.sealed(conn, sid) == sealed
    assert conn.execute("SELECT count(*) FROM study_dataset").fetchone()[0] == 1


def test_a_rewritten_bar_from_before_the_pin_is_caught_by_the_next_run(env):
    conn, owner = env
    sid = register_study(conn, owner, small_spec(), NOW)
    study_runner.prepare(conn, small_spec(), sid)
    conn.execute("SELECT set_config('algo.allow_frozen_write', 'on', false)")
    conn.execute(
        "UPDATE bar_1d SET close = close + 1 WHERE instrument_id = (SELECT min(instrument_id) FROM bar_1d)"
    )
    with pytest.raises(StudyRunError, match="has changed"):
        study_runner.prepare(conn, small_spec(), sid)


def test_a_correction_ingested_after_the_pin_is_invisible_and_the_study_still_reproduces(env):
    conn, owner = env
    sid = register_study(conn, owner, small_spec(), NOW)
    setup = study_runner.prepare(conn, small_spec(), sid)
    iid = setup.membership.ever()[0]
    before = setup.reader.load(iid).rows[-1][4]
    conn.execute("SELECT set_config('algo.allow_frozen_write', 'on', false)")
    conn.execute(
        "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,adjusted_through,dataset_version,ingested_at)"
        " SELECT instrument_id,ts,open,high,low,close + 50,volume,source,adjusted_through,dataset_version + 1,%s"
        " FROM bar_1d WHERE instrument_id=%s ORDER BY ts DESC LIMIT 1",
        (NOW + timedelta(days=1), iid),
    )
    again = study_runner.prepare(
        conn, small_spec(), sid
    )  # the provider's correction came after the study's moment
    assert again.reader.load(iid).rows[-1][4] == before and isinstance(again.reader, ResearchReader)
    unpinned = holdout_lock.ResearchReader(
        __import__("algo.data.reader", fromlist=["BarReader"]).BarReader(
            conn, source="kite", publish_lag=timedelta(0)
        ),
        holdout_lock.require(conn),
    )
    assert unpinned.load(iid).rows[-1][4] == before + D(
        50
    )  # without the pin the correction would have changed the study


def test_a_study_from_before_pinning_is_refused_with_the_way_forward(env):
    conn, owner = env
    spec = small_spec()
    legacy = registry.register(
        conn, name="old", strategy_id=spec.strategy_id, hypothesis="h", style="long_only", param_ranges={"a": [1, 2]},
        holdout=(spec.holdout_start, spec.end), now=NOW,
        study={"spec": spec.model_dump(mode="json"), "combinations": [], "data_freeze": {}, "cost_schedules": []},
    )  # fmt: skip
    with pytest.raises(StudyRunError, match="predates dataset pinning"):
        study_runner.prepare(conn, spec, legacy)


def test_the_sealed_dataset_cannot_be_changed_or_deleted(env):
    conn, owner = env
    sid = register_study(conn, owner, small_spec(), NOW)
    study_runner.prepare(conn, small_spec(), sid)
    for sql in ("UPDATE study_dataset SET dataset_sha256 = 'x'", "DELETE FROM study_dataset"):
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute(sql)
