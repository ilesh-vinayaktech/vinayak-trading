# ruff: noqa: E501
from datetime import UTC, datetime

import psycopg
import pytest

from algo.alpha import registry
from algo.alpha.discover import Evidence
from algo.data.store.migrate import migrate
from algo.learning import memory

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


def test_notes_are_stored_cleaned_and_found_by_every_filter(conn):
    migrate(conn)
    a = memory.add(
        conn,
        "FAILURE",
        "alpha:ret_5d:h5",
        "No edge after costs",
        by="jane",
        now=NOW,
        tags=[" Alpha ", "COSTS", "alpha", ""],
    )
    b = memory.add(
        conn, "DECISION", "capital", "Personal capital only, 100% of it", by="jane", now=NOW
    )
    n = memory.search(conn)[1]
    assert (n.note_id, n.tags, n.created_by) == (a, ["alpha", "costs"], "jane")
    assert [x.note_id for x in memory.search(conn)] == [b, a]  # newest first
    assert [x.note_id for x in memory.search(conn, text="EDGE")] == [a]
    assert [x.note_id for x in memory.search(conn, tags=["costs", "alpha"])] == [a]
    assert memory.search(conn, tags=["costs", "missing"]) == []
    assert [x.note_id for x in memory.search(conn, kind="DECISION")] == [b]
    assert [x.note_id for x in memory.search(conn, subject_prefix="alpha:")] == [a]
    assert memory.search(conn, subject_prefix="lpha:") == []  # a prefix, not a substring
    assert len(memory.search(conn, limit=1)) == 1
    assert [x.note_id for x in memory.search(conn, text="100%")] == [b]  # % is literal
    assert memory.search(conn, text="1_0%") == []  # and so is _


def test_bad_notes_are_refused(conn):
    migrate(conn)
    for kind, subject, body, by in (
        ("OPINION", "s", "b", "j"),
        ("FINDING", " ", "b", "j"),
        ("FINDING", "s", " ", "j"),
        ("FINDING", "s", "b", " "),
    ):
        with pytest.raises(ValueError):
            memory.add(conn, kind, subject, body, by=by, now=NOW)
    assert conn.execute("SELECT count(*) FROM research_note").fetchone() == (0,)


def test_notes_are_never_changed_or_removed(conn):
    migrate(conn)
    memory.add(conn, "LESSON", "s", "b", by="j", now=NOW)
    for sql in ("UPDATE research_note SET body='x'", "DELETE FROM research_note"):
        with pytest.raises(psycopg.errors.RaiseException, match="insert-only"):
            conn.execute(sql)


def test_alpha_hypotheses_become_notes_once_each(conn):
    migrate(conn)
    good = Evidence("ret_5d", "1", 5, 500, 150.0, 0.05, 0.1, 0.5, 0.6, 4.0, 0.0001)
    bad = Evidence("ret_20d", "1", 20, 500, 150.0, 0.0, 0.1, 0.0, 0.5, 0.0, 0.9)
    registry.record(conn, [good, bad], "d" * 64, NOW)
    assert memory.sync_alpha(conn, now=NOW) == 2 and memory.sync_alpha(conn, now=NOW) == 0
    fail = memory.search(conn, kind="FAILURE")
    find = memory.search(conn, kind="FINDING")
    assert (
        [f.subject for f in fail] == ["alpha:ret_20d:h20"]
        and "REJECTED" in fail[0].body
        and "rejected" in fail[0].tags
    )
    assert [f.subject for f in find] == ["alpha:ret_5d:h5"] and "CANDIDATE" in find[0].body
    registry.record(
        conn,
        [Evidence("ret_60d", "1", 60, 500, 150.0, 0.0, 0.1, 0.0, 0.5, 0.0, 0.9)],
        "e" * 64,
        NOW,
    )
    assert memory.sync_alpha(conn, now=NOW) == 1  # only the new one
