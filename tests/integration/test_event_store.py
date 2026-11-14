from datetime import UTC, datetime
from decimal import Decimal as D

import psycopg
import pytest

from algo.data.store.migrate import migrate
from algo.execution.event_store import DbStore, MemoryStore
from algo.execution.orders import OrderEvent, State, replay

pytestmark = pytest.mark.integration
T = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)


def ev(oid, seq, state=None, kind="STATE", **data):
    return OrderEvent(oid, seq, T, state, kind, data)


def history(oid):
    return [
        ev(
            oid,
            0,
            None,
            "NEW",
            strategy_id="s1",
            instrument_id=7,
            side="BUY",
            qty=10,
            price=D("100.50"),
        ),
        ev(oid, 1, State.SUBMITTING),
        ev(oid, 2, State.SUBMITTED, broker_order_id="B1"),
        ev(oid, 3, None, "NOTE", text="hello", at=T),
        ev(oid, 4, State.PARTIALLY_FILLED, filled_qty=4, avg_price=D("100.4999999999")),
    ]


@pytest.fixture
def db(conn):
    migrate(conn)
    return conn


def test_the_memory_store_keeps_nothing_between_runs():
    s = MemoryStore()
    s.append(history("o1")[0])
    assert s.load() == {}


def test_events_come_back_from_the_database_exactly_and_replay_to_the_same_order(db):
    s = DbStore(db)
    for e in history("o1") + history("o2")[:2]:
        s.append(e)
    loaded = DbStore(db).load()  # a fresh object, as after a restart
    assert sorted(loaded) == ["o1", "o2"]
    assert loaded["o1"] == history("o1")  # Decimals, times and ints are exactly as written
    assert (
        replay(loaded["o1"]).avg_price == D("100.4999999999")
        and replay(loaded["o2"]).state is State.SUBMITTING
    )


def test_an_event_cannot_be_written_twice_edited_or_deleted(db):
    s = DbStore(db)
    s.append(history("o1")[0])
    with pytest.raises(psycopg.errors.UniqueViolation):
        s.append(history("o1")[0])  # the same (order, sequence) again
    for sql in ("UPDATE oms_event SET kind='X'", "DELETE FROM oms_event"):
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            db.execute(sql)
