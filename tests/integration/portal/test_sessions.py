import base64
from datetime import UTC, datetime, timedelta

import pytest

from algo.data.store.migrate import migrate
from algo.portal import accounts, sessions, totp
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


def test_a_session_is_found_by_its_token_only_and_stores_no_secret_in_clear(db):
    uid = make(db)
    token, csrf = sessions.create(
        db, uid, now=NOW, mfa_verified=False, ip="1.1.1.1", user_agent="ua"
    )
    s = sessions.lookup(db, token, NOW + timedelta(minutes=5))
    assert (
        s is not None and s.user_id == uid and s.role == "TRADER" and s.email == "jane@example.com"
    )
    assert sessions.lookup(db, token + "x", NOW) is None and sessions.lookup(db, "", NOW) is None
    stored = " ".join(
        str(v)
        for v in db.execute("SELECT token_hash, csrf_token_hash FROM portal_session").fetchone()
    )
    assert token not in stored and csrf not in stored
    assert (
        sessions.csrf_ok(s, csrf)
        and not sessions.csrf_ok(s, "wrong")
        and not sessions.csrf_ok(s, None)
        and not sessions.csrf_ok(s, "")
    )


def test_sessions_expire_when_idle_or_at_the_absolute_limit_and_the_touch_is_throttled(db):
    uid = make(db)
    token, _ = sessions.create(db, uid, now=NOW, mfa_verified=False, ip=None, user_agent=None)
    sessions.lookup(db, token, NOW + timedelta(seconds=30))  # within a minute: not rewritten
    assert db.execute("SELECT last_seen_at FROM portal_session").fetchone() == (NOW,)
    sessions.lookup(db, token, NOW + timedelta(minutes=10))
    assert db.execute("SELECT last_seen_at FROM portal_session").fetchone() == (
        NOW + timedelta(minutes=10),
    )
    assert (
        sessions.lookup(
            db, token, NOW + timedelta(minutes=10) + sessions.IDLE + timedelta(seconds=1)
        )
        is None
    )  # idle
    t = NOW + timedelta(minutes=10)
    while t < NOW + sessions.ABSOLUTE:  # keep it busy: still dead at 12 hours
        t += timedelta(minutes=20)
        sessions.lookup(db, token, min(t, NOW + sessions.ABSOLUTE - timedelta(seconds=1)))
    assert sessions.lookup(db, token, NOW + sessions.ABSOLUTE + timedelta(seconds=1)) is None


def test_revoking_one_or_all_sessions_and_suspending_the_user_ends_them(db):
    uid = make(db)
    t1, _ = sessions.create(db, uid, now=NOW, mfa_verified=False, ip=None, user_agent=None)
    t2, _ = sessions.create(db, uid, now=NOW, mfa_verified=False, ip=None, user_agent=None)
    t3, _ = sessions.create(db, uid, now=NOW, mfa_verified=False, ip=None, user_agent=None)
    s1, s2 = sessions.lookup(db, t1, NOW), sessions.lookup(db, t2, NOW)
    assert len(sessions.active_for(db, uid, NOW)) == 3
    sessions.revoke(db, s1.session_id, NOW)
    assert sessions.lookup(db, t1, NOW) is None
    assert (
        sessions.revoke_user_sessions(db, uid, NOW, keep=s2.session_id) == 1
    )  # t3 ends, t2 is kept
    assert sessions.lookup(db, t2, NOW) is not None and sessions.lookup(db, t3, NOW) is None
    db.execute("UPDATE portal_user SET status='SUSPENDED' WHERE user_id=%s", (uid,))
    assert (
        sessions.lookup(db, t2, NOW) is None
    )  # a suspended account's live session stops working at once
    assert sessions.revoke_user_sessions(db, uid, NOW) == 1  # no keep: ends everything left
