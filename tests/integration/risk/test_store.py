from datetime import UTC, datetime

import psycopg
import pytest

from algo.data.store.migrate import migrate
from algo.risk import store
from algo.risk.killswitch import KillSwitchError, Mode

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)


@pytest.fixture
def db(conn):
    migrate(conn)
    return conn


def test_a_new_database_has_a_running_switch(db):
    k = store.load(db)
    assert k.mode("anyone") is Mode.RUNNING and k.events == []


def test_every_change_is_stored_and_survives_a_reload(db):
    store.change(db, "pause", "s1", by="jane", reason="looking", now=NOW)
    store.change(db, "cancel", None, by="joe", reason="data problem", now=NOW)
    k = store.load(db)  # a fresh load, as after a restart
    assert k.mode("s1") is Mode.CANCEL and k.mode("s2") is Mode.CANCEL
    assert [(e.scope, e.mode, e.by, e.reason) for e in k.events] == [
        ("s1", Mode.PAUSE, "jane", "looking"),
        (None, Mode.CANCEL, "joe", "data problem"),
    ]
    store.change(db, "resume", None, by="joe", reason="fixed", now=NOW)
    assert store.load(db).mode("s2") is Mode.RUNNING and store.load(db).mode("s1") is Mode.PAUSE


def test_flatten_is_stored_only_with_the_explicit_override(db):
    with pytest.raises(KillSwitchError, match="override"):
        store.change(db, "flatten", "s1", by="jane", reason="fire", now=NOW)
    assert store.load(db).events == []
    store.change(db, "flatten", "s1", by="jane", reason="fire", now=NOW, emergency_override=True)
    assert store.load(db).mode("s1") is Mode.FLATTEN


def test_an_unknown_operation_is_refused(db):
    with pytest.raises(ValueError, match="unknown operation"):
        store.change(db, "explode", None, by="jane", reason="x", now=NOW)


def test_the_log_cannot_be_edited_or_deleted_and_needs_a_who_and_a_why(db):
    store.change(db, "pause", None, by="jane", reason="r", now=NOW)
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        db.execute("UPDATE kill_switch_event SET reason='x'")
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        db.execute("DELETE FROM kill_switch_event")
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO kill_switch_event (ts, mode, by_who, reason) VALUES (%s,'PAUSE',' ','r')",
            (NOW,),
        )
