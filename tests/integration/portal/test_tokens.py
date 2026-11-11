from datetime import UTC, datetime, timedelta

import pytest

from algo.data.store.migrate import migrate
from algo.portal import accounts, tokens
from tests.support.portal import FAST

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)


@pytest.fixture
def uid(conn):
    migrate(conn)
    return accounts.create_user(
        conn,
        FAST,
        email="a@example.com",
        display_name="A B",
        role="VIEWER",
        password=None,
        now=NOW,
        status="INVITED",
    )


def test_a_token_works_once_for_its_own_purpose_and_is_stored_only_as_a_hash(conn, uid):
    raw = tokens.issue(conn, uid, "INVITE", NOW)
    assert raw not in str(conn.execute("SELECT * FROM portal_token").fetchall())
    assert tokens.consume(conn, raw, "RESET", NOW) is None  # a reset needs a reset token
    assert tokens.consume(conn, raw, "INVITE", NOW) == uid
    assert tokens.consume(conn, raw, "INVITE", NOW) is None  # spent
    assert tokens.consume(conn, "nonsense", "INVITE", NOW) is None


def test_a_token_expires_and_a_newer_one_retires_the_older(conn, uid):
    old = tokens.issue(conn, uid, "RESET", NOW)
    assert tokens.consume(conn, old, "RESET", NOW + tokens.RESET_TTL + timedelta(seconds=1)) is None
    first = tokens.issue(conn, uid, "RESET", NOW)
    second = tokens.issue(conn, uid, "RESET", NOW)
    assert (
        tokens.consume(conn, first, "RESET", NOW) is None
        and tokens.consume(conn, second, "RESET", NOW) == uid
    )


def test_issued_since_counts_tokens_in_a_window(conn, uid):
    tokens.issue(conn, uid, "RESET", NOW - timedelta(hours=2))
    tokens.issue(conn, uid, "RESET", NOW - timedelta(minutes=5))
    tokens.issue(conn, uid, "INVITE", NOW - timedelta(minutes=5))
    assert tokens.issued_since(conn, uid, "RESET", NOW - timedelta(hours=1)) == 1
