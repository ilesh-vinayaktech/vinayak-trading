import base64
from datetime import UTC, datetime

import psycopg
import pytest

from algo.data.store.migrate import migrate
from algo.portal import accounts, audit, totp
from algo.portal.crypto import KeyRing
from algo.portal.passwords import Hasher

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)
FAST = Hasher(time_cost=1, memory_cost=8, parallelism=1)
RING = KeyRing.from_env(
    {"ALGO_VAULT_KEYS": "v1:" + base64.b64encode(b"k" * 32).decode(), "ALGO_VAULT_CURRENT": "v1"}
)
PW = "violet-harbor-lantern-42"


@pytest.fixture
def db(conn):
    migrate(conn)
    return conn


def make(db, email="jane@example.com", role="TRADER", password=PW, **kw):
    return accounts.create_user(
        db, FAST, email=email, display_name="Jane Roe", role=role, password=password, now=NOW, **kw
    )


def login(db, *, email="jane@example.com", password=PW, code=None, now=NOW, ip="203.0.113.7"):
    return accounts.authenticate(
        db,
        FAST,
        RING,
        email=email,
        password=password,
        totp_code=code,
        ip=ip,
        user_agent="pytest",
        now=now,
    )


def enrol(db, uid, now=NOW):
    secret, uri = accounts.begin_mfa_enrolment(db, RING, user_id=uid)
    codes = accounts.confirm_mfa(
        db, RING, user_id=uid, code=totp.code_at(secret, int(now.timestamp()) // 30), now=now
    )
    return secret, uri, codes


def test_the_audit_trail_records_and_filters_and_can_never_be_changed(db):
    uid = make(db)
    a = audit.record(
        db,
        now=NOW,
        action="thing.done",
        actor_user_id=uid,
        actor_label="jane",
        target_type="user",
        target_id="7",
        detail={"k": 1},
        ip="1.2.3.4",
        user_agent="x" * 500,
    )
    audit.record(db, now=NOW, action="other_thing", target_type="ticket", target_id="9")
    rows = audit.recent(db, limit=10)
    assert [r["action"] for r in rows][:2] == ["other_thing", "thing.done"]
    assert audit.recent(db, actor_user_id=uid, action_prefix="thing.")[0]["id"] == a
    assert audit.recent(db, target_type="ticket", target_id="9")[0]["action"] == "other_thing"
    assert (
        audit.recent(db, action_prefix="%") == []
    )  # wildcard characters are escaped, not interpreted
    assert db.execute(
        "SELECT length(user_agent) FROM portal_audit WHERE audit_id=%s", (a,)
    ).fetchone() == (300,)
    assert len(audit.recent(db, limit=0)) == 1  # a limit below 1 is raised to 1
    for sql in (
        "UPDATE portal_audit SET action='x'",
        "DELETE FROM portal_audit",
        "TRUNCATE portal_audit",
    ):
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            db.execute(sql)
