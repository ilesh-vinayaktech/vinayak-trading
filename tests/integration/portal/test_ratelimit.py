import base64
from datetime import UTC, datetime, timedelta

import pytest

from algo.data.store.migrate import migrate
from algo.portal import accounts, ratelimit, totp
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


def test_an_account_is_blocked_after_five_failures_and_a_success_or_time_clears_it(db):
    for _ in range(4):
        ratelimit.record(db, "A@Example.com", "1.1.1.1", success=False, now=NOW)
    assert not ratelimit.blocked(db, "a@example.com", "9.9.9.9", NOW)  # email is case-insensitive
    ratelimit.record(db, "a@example.com", "1.1.1.1", success=False, now=NOW)
    assert ratelimit.blocked(db, "a@example.com", "9.9.9.9", NOW)
    assert not ratelimit.blocked(
        db, "a@example.com", None, NOW + ratelimit.WINDOW + timedelta(seconds=1)
    )  # window passed
    ratelimit.record(db, "a@example.com", "1.1.1.1", success=True, now=NOW + timedelta(minutes=1))
    assert not ratelimit.blocked(
        db, "a@example.com", None, NOW + timedelta(minutes=2)
    )  # a success starts a fresh count


def test_an_address_is_blocked_after_thirty_failures_across_accounts(db):
    for i in range(ratelimit.IP_FAILURES):
        ratelimit.record(db, f"user{i}@example.com", "5.5.5.5", success=False, now=NOW)
    assert ratelimit.blocked(db, "fresh@example.com", "5.5.5.5", NOW)
    assert not ratelimit.blocked(db, "fresh@example.com", "6.6.6.6", NOW)
    assert not ratelimit.blocked(db, "fresh@example.com", None, NOW)
