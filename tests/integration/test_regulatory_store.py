from datetime import date

import psycopg
import pytest

from algo.data.store.migrate import migrate
from algo.execution.regulatory import REQUIRED, Item, check, in_force, record

pytestmark = pytest.mark.integration
TODAY = date(2026, 11, 16)


def item(topic, verified, value=1):
    return Item(
        "NSE", "CM", topic, {"limit": value}, date(2026, 4, 1), "circular", verified, "owner"
    )


def test_the_newest_row_per_topic_is_in_force_and_a_recheck_is_a_new_row(conn):
    migrate(conn)
    assert check(conn, TODAY) != []  # nothing recorded: live stays blocked
    for t in REQUIRED:
        record(conn, item(t, date(2026, 9, 1)))
    assert len(check(conn, TODAY)) == len(REQUIRED)  # all older than 30 days
    record(conn, item("ops_limit", TODAY, value=10))  # re-checked, and the limit changed
    by_topic = {i.topic: i for i in in_force(conn)}
    assert (
        by_topic["ops_limit"].value == {"limit": 10}
        and by_topic["ops_limit"].last_verified == TODAY
    )
    assert len(check(conn, TODAY)) == len(REQUIRED) - 1
    count = conn.execute("SELECT count(*) FROM regulatory_config").fetchone()[0]
    assert count == len(REQUIRED) + 1  # the old row is kept


def test_rows_cannot_be_changed_or_deleted(conn):
    migrate(conn)
    record(conn, item("ops_limit", TODAY))
    for sql in ("UPDATE regulatory_config SET source='x'", "DELETE FROM regulatory_config"):
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute(sql)
