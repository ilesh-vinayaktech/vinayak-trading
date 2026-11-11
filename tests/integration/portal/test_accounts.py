import base64
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from algo.data.store.migrate import migrate
from algo.portal import accounts, audit, ratelimit, sessions, totp
from algo.portal.crypto import KeyRing
from algo.portal.passwords import Hasher, PasswordPolicyError

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


def test_creating_users_validates_input_normalises_email_and_refuses_duplicates(db):
    uid = make(db, email="  Jane@Example.COM ")
    assert db.execute(
        "SELECT email, status FROM portal_user WHERE user_id=%s", (uid,)
    ).fetchone() == ("jane@example.com", "ACTIVE")
    with pytest.raises(accounts.DuplicateUser):
        make(db, email="JANE@example.com")
    for bad in ("nope", "a@b", "x" * 250 + "@example.com"):
        with pytest.raises(accounts.AccountError, match="valid email"):
            make(db, email=bad)
    with pytest.raises(accounts.AccountError, match="unknown role"):
        make(db, email="b@example.com", role="ROOT")
    with pytest.raises(accounts.AccountError, match="name"):
        accounts.create_user(
            db, FAST, email="c@example.com", display_name=" ", role="VIEWER", password=PW, now=NOW
        )
    with pytest.raises(PasswordPolicyError):
        make(db, email="d@example.com", password="short")
    invited = make(
        db, email="e@example.com", password=None, status="INVITED", created_by=uid
    )  # an invitation has no password yet
    assert db.execute(
        "SELECT password_hash, password_changed_at FROM portal_user WHERE user_id=%s", (invited,)
    ).fetchone() == (None, None)
    assert audit.recent(db, action_prefix="user.create", limit=1)[0]["target_id"] == str(invited)


def test_a_correct_login_creates_a_session_and_an_audit_entry(db):
    uid = make(db)
    r = login(db)
    assert (r.status, r.user_id) == ("ok", uid) and r.token and r.csrf
    assert sessions.lookup(db, r.token, NOW).mfa_verified is False
    assert db.execute(
        "SELECT last_login_at FROM portal_user WHERE user_id=%s", (uid,)
    ).fetchone() == (NOW,)
    assert audit.recent(db, action_prefix="auth.login", limit=1)[0]["actor_user_id"] == uid


def test_every_kind_of_bad_login_looks_the_same_and_counts_toward_the_limit(db):
    make(db)
    make(db, email="gone@example.com", password=None, status="INVITED")  # no password set yet
    make(db, email="held@example.com")
    db.execute("UPDATE portal_user SET status='SUSPENDED' WHERE email='held@example.com'")
    cases = [
        dict(password="wrong-password-123"),  # wrong password
        dict(email="nobody@example.com"),  # unknown user
        dict(email="not an email"),  # not even an address
        dict(email="gone@example.com"),  # invited, no password
        dict(email="held@example.com"),  # suspended
    ]
    assert [login(db, **c).status for c in cases] == ["invalid"] * 5
    assert audit.recent(db, action_prefix="auth.login_failed")  # recorded
    assert db.execute("SELECT count(*) FROM portal_login_attempt").fetchone() == (
        4,
    )  # the malformed address never reaches the table


def test_five_wrong_passwords_block_even_the_right_one_until_the_window_passes(db):
    make(db)
    for _ in range(5):
        assert login(db, password="wrong-password-123").status == "invalid"
    assert login(db).status == "blocked"  # the correct password is not even checked
    assert audit.recent(db, action_prefix="auth.blocked", limit=1)
    assert login(db, now=NOW + ratelimit.WINDOW + timedelta(seconds=1)).status == "ok"


def test_a_login_with_old_hash_settings_upgrades_the_stored_hash(db):
    uid = make(db)
    old = db.execute("SELECT password_hash FROM portal_user WHERE user_id=%s", (uid,)).fetchone()[0]
    stronger = Hasher(time_cost=2, memory_cost=16, parallelism=1)
    r = accounts.authenticate(
        db,
        stronger,
        RING,
        email="jane@example.com",
        password=PW,
        totp_code=None,
        ip=None,
        user_agent=None,
        now=NOW,
    )
    assert r.status == "ok"
    new = db.execute("SELECT password_hash FROM portal_user WHERE user_id=%s", (uid,)).fetchone()[0]
    assert new != old and not stronger.needs_rehash(new)


def test_enrolling_a_second_factor_needs_a_valid_code_and_gives_ten_recovery_codes(db):
    uid = make(db, role="ADMIN")
    assert (
        accounts.needs_enrolment("ADMIN", False)
        and not accounts.needs_enrolment("ADMIN", True)
        and not accounts.needs_enrolment("TRADER", False)
    )
    with pytest.raises(accounts.MfaError, match="start the enrolment"):
        accounts.confirm_mfa(db, RING, user_id=uid, code="123456", now=NOW)
    secret, uri = accounts.begin_mfa_enrolment(db, RING, user_id=uid)
    assert uri.startswith("otpauth://totp/Vinayak%20Trading:jane%40example.com") and secret in uri
    stored = db.execute(
        "SELECT totp_secret_enc, totp_enabled FROM portal_user WHERE user_id=%s", (uid,)
    ).fetchone()
    assert secret not in stored[0] and stored[1] is False  # encrypted, and not active yet
    with pytest.raises(accounts.MfaError, match="not right"):
        accounts.confirm_mfa(db, RING, user_id=uid, code="000000", now=NOW)
    codes = accounts.confirm_mfa(
        db, RING, user_id=uid, code=totp.code_at(secret, int(NOW.timestamp()) // 30), now=NOW
    )
    assert len(codes) == 10 and db.execute(
        "SELECT count(*) FROM portal_recovery_code WHERE user_id=%s", (uid,)
    ).fetchone() == (10,)
    assert not any(
        c in str(db.execute("SELECT code_hash FROM portal_recovery_code").fetchall()) for c in codes
    )  # hashes only
    with pytest.raises(accounts.MfaError, match="already on"):
        accounts.begin_mfa_enrolment(db, RING, user_id=uid)
    with pytest.raises(accounts.MfaError, match="start the enrolment"):
        accounts.confirm_mfa(db, RING, user_id=uid, code="123456", now=NOW)  # already confirmed
    with pytest.raises(accounts.AccountError, match="unknown user"):
        accounts.begin_mfa_enrolment(db, RING, user_id=uuid4())
    with pytest.raises(accounts.MfaError):
        accounts.confirm_mfa(db, RING, user_id=uuid4(), code="123456", now=NOW)


def test_login_with_a_second_factor_asks_for_the_code_then_checks_it_once(db):
    uid = make(db, role="ADMIN")
    secret, _, codes = enrol(db, uid)
    assert (
        login(db).status == "mfa_required"
    )  # password right, no code yet: no session, no failure counted
    assert db.execute("SELECT count(*) FROM portal_session").fetchone() == (0,)
    later = NOW + timedelta(
        seconds=90
    )  # a fresh step, so the enrolment code is not what is being replayed
    good = totp.code_at(secret, int(later.timestamp()) // 30)
    r = login(db, code=good, now=later)
    assert r.status == "ok" and sessions.lookup(db, r.token, later).mfa_verified is True
    assert (
        login(db, code=good, now=later).status == "mfa_invalid"
    )  # the same code cannot be used again
    assert login(db, code="000000", now=later).status == "mfa_invalid"
    # a one-time recovery code works exactly once
    assert login(db, code=codes[0], now=later).status == "ok"
    assert login(db, code=codes[0], now=later).status == "mfa_invalid"
    assert (
        login(db, code=codes[1].upper().replace("-", " "), now=later).status == "ok"
    )  # case and separators are forgiven
    assert audit.recent(db, action_prefix="auth.recovery_code_used", limit=1)


def test_an_unreadable_second_factor_seed_never_lets_anyone_in(db):
    uid = make(db, role="ADMIN")
    enrol(db, uid)
    db.execute("UPDATE portal_user SET totp_secret_enc='v1.AAAA' WHERE user_id=%s", (uid,))
    assert login(db, code="123456").status == "mfa_invalid"


def test_changing_the_password_checks_the_old_one_the_policy_and_ends_other_sessions(db):
    uid = make(db)
    r1, r2 = login(db), login(db)
    keep = sessions.lookup(db, r1.token, NOW).session_id
    new = "amber-meadow-kettle-77"
    with pytest.raises(accounts.AccountError, match="current password"):
        accounts.change_password(
            db, FAST, user_id=uid, current="not-my-password-1", new=new, now=NOW, keep_session=keep
        )
    with pytest.raises(accounts.AccountError, match="not used"):
        accounts.change_password(
            db, FAST, user_id=uid, current=PW, new=PW, now=NOW, keep_session=keep
        )
    with pytest.raises(PasswordPolicyError):
        accounts.change_password(
            db, FAST, user_id=uid, current=PW, new="short", now=NOW, keep_session=keep
        )
    db.execute("UPDATE portal_user SET must_change_password=true WHERE user_id=%s", (uid,))
    accounts.change_password(db, FAST, user_id=uid, current=PW, new=new, now=NOW, keep_session=keep)
    assert (
        sessions.lookup(db, r1.token, NOW) is not None
        and sessions.lookup(db, r2.token, NOW) is None
    )
    assert db.execute(
        "SELECT must_change_password FROM portal_user WHERE user_id=%s", (uid,)
    ).fetchone() == (False,)
    assert login(db, password=PW).status == "invalid" and login(db, password=new).status == "ok"
    assert audit.recent(db, action_prefix="auth.password_changed", limit=1)[0]["detail"] == {
        "other_sessions_ended": 1
    }
    with pytest.raises(accounts.AccountError, match="current password"):
        accounts.change_password(
            db, FAST, user_id=uuid4(), current=PW, new=new, now=NOW, keep_session=None
        )
