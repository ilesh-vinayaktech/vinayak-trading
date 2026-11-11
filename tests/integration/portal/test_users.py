from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from algo.data.store.migrate import migrate
from algo.portal import accounts, audit, sessions, totp, users
from algo.portal.mailer import ConsoleMailer
from algo.portal.passwords import PasswordPolicyError
from tests.support.portal import FAST, RING

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)
PW = "violet-harbor-lantern-42"
URL = "https://portal.example/"


@pytest.fixture
def db(conn):
    migrate(conn)
    return conn


def make(db, email, role="TRADER", name="Test Person", status="ACTIVE"):
    return accounts.create_user(
        db, FAST, email=email, display_name=name, role=role, password=PW, now=NOW, status=status
    )


def test_the_directory_searches_filters_pages_and_validates(db):
    make(db, "ada@example.com", "ADMIN", "Ada Admin")
    make(db, "bob@example.com", "TRADER", "Bob Trader")
    make(db, "cy_100%@example.com", "VIEWER", "Cy Viewer", status="SUSPENDED")
    everyone = users.list_users(db)
    assert everyone["total"] == 3 and [u["name"] for u in everyone["items"]] == [
        "Ada Admin",
        "Bob Trader",
        "Cy Viewer",
    ]
    assert [u["email"] for u in users.list_users(db, q="TRAD")["items"]] == [
        "bob@example.com"
    ]  # name, case-insensitive
    assert (
        users.list_users(db, q="%")["total"] == 1
    )  # a wildcard is searched for literally (only the % in cy_100%)
    assert users.list_users(db, q="_")["total"] == 1
    assert [u["name"] for u in users.list_users(db, role="ADMIN")["items"]] == ["Ada Admin"]
    assert [u["name"] for u in users.list_users(db, status="SUSPENDED")["items"]] == ["Cy Viewer"]
    page = users.list_users(db, limit=1, offset=1)
    assert page["total"] == 3 and [u["name"] for u in page["items"]] == ["Bob Trader"]
    assert (
        len(users.list_users(db, limit=0)["items"]) == 1
        and users.list_users(db, offset=-5)["items"][0]["name"] == "Ada Admin"
    )
    for bad in (dict(role="ROOT"), dict(status="GONE")):
        with pytest.raises(users.UserError):
            users.list_users(db, **bad)


def test_a_profile_shows_security_state_sessions_and_who_created_the_account(db):
    boss = make(db, "boss@example.com", "ADMIN", "The Boss")
    uid, _ = users.invite(
        db,
        FAST,
        ConsoleMailer(),
        URL,
        actor=boss,
        email="new@example.com",
        name="New Hire",
        role="TRADER",
        now=NOW,
    )
    sessions.create(db, boss, now=NOW, mfa_verified=False, ip=None, user_agent=None)
    p = users.get_user(db, uid, NOW)
    assert (
        p["email"],
        p["status"],
        p["role"],
        p["created_by"],
        p["active_sessions"],
        p["mfa_enabled"],
    ) == ("new@example.com", "INVITED", "TRADER", "The Boss", 0, False)
    assert (
        users.get_user(db, boss, NOW)["active_sessions"] == 1
        and users.get_user(db, boss, NOW)["created_by"] is None
    )
    with pytest.raises(users.UserError) as e:
        users.get_user(db, uuid4(), NOW)
    assert e.value.status == 404


def test_an_invitation_creates_a_pending_account_mails_a_link_and_is_accepted_once(db):
    boss, mail = make(db, "boss@example.com", "ADMIN"), ConsoleMailer()
    uid, url = users.invite(
        db,
        FAST,
        mail,
        URL,
        actor=boss,
        email=" New@Example.com ",
        name="New Hire",
        role="OPERATOR",
        now=NOW,
    )
    assert (
        url.startswith("https://portal.example/accept-invite?token=")
        and mail.sent[0].to == "new@example.com"
        and url in mail.sent[0].body
    )
    assert db.execute(
        "SELECT status, password_hash FROM portal_user WHERE user_id=%s", (uid,)
    ).fetchone() == ("INVITED", None)
    token = url.split("token=")[1]
    with pytest.raises(PasswordPolicyError):
        users.accept_invite(
            db, FAST, token=token, password="short", now=NOW
        )  # the token was spent by that attempt...
    again = users.reissue_invite(
        db, mail, URL, actor=boss, user_id=uid, now=NOW
    )  # ...so an admin sends a fresh one
    token = again.split("token=")[1]
    assert users.accept_invite(db, FAST, token=token, password=PW, now=NOW) == uid
    assert db.execute("SELECT status FROM portal_user WHERE user_id=%s", (uid,)).fetchone() == (
        "ACTIVE",
    )
    with pytest.raises(users.UserError, match="not valid"):
        users.accept_invite(db, FAST, token=token, password=PW, now=NOW)  # a link works once
    with pytest.raises(users.UserError, match="only a pending"):
        users.reissue_invite(db, mail, URL, actor=boss, user_id=uid, now=NOW)
    for kind in ("user.invited", "user.invite_resent", "user.invite_accepted"):
        assert audit.recent(db, action_prefix=kind)


def test_invitations_refuse_duplicates_bad_input_and_a_token_for_an_account_that_is_no_longer_pending(
    db,
):
    boss, mail = make(db, "boss@example.com", "ADMIN"), ConsoleMailer()
    with pytest.raises(users.UserError) as e:
        users.invite(
            db,
            FAST,
            mail,
            URL,
            actor=boss,
            email="BOSS@example.com",
            name="Dup",
            role="VIEWER",
            now=NOW,
        )
    assert e.value.status == 409
    for bad in (dict(email="nope"), dict(role="ROOT"), dict(name=" ")):
        args = dict(email="x@example.com", name="X Y", role="VIEWER") | bad
        with pytest.raises(users.UserError) as e2:
            users.invite(db, FAST, mail, URL, actor=boss, now=NOW, **args)
        assert e2.value.status == 422
    uid, url = users.invite(
        db,
        FAST,
        mail,
        URL,
        actor=boss,
        email="p@example.com",
        name="Pend Ing",
        role="VIEWER",
        now=NOW,
    )
    users.set_status(
        db, actor=boss, user_id=uid, status="DISABLED", now=NOW
    )  # the invitation is withdrawn
    with pytest.raises(users.UserError, match="not valid"):
        users.accept_invite(db, FAST, token=url.split("token=")[1], password=PW, now=NOW)
    with pytest.raises(users.UserError) as e3:
        users.reissue_invite(db, mail, URL, actor=boss, user_id=uuid4(), now=NOW)
    assert e3.value.status == 404


def test_forgot_password_looks_the_same_for_everyone_and_sends_only_for_an_active_account_within_the_limit(
    db,
):
    make(db, "jane@example.com")
    make(db, "held@example.com", status="SUSPENDED")
    mail = ConsoleMailer()
    for e in ("jane@example.com", "ghost@example.com", "held@example.com", "not-an-email"):
        assert users.request_reset(db, mail, URL, email=e, now=NOW) is None
    assert [m.to for m in mail.sent] == ["jane@example.com"]
    for _ in range(5):
        users.request_reset(db, mail, URL, email="jane@example.com", now=NOW)
    assert len(mail.sent) == users.RESET_LIMIT  # then it goes quiet
    users.request_reset(
        db, mail, URL, email="jane@example.com", now=NOW + users.RESET_WINDOW + timedelta(seconds=1)
    )
    assert len(mail.sent) == users.RESET_LIMIT + 1


def test_a_reset_link_sets_a_new_password_once_and_signs_every_session_out(db):
    uid, mail = make(db, "jane@example.com"), ConsoleMailer()
    token_s, _ = sessions.create(db, uid, now=NOW, mfa_verified=False, ip=None, user_agent=None)
    users.request_reset(db, mail, URL, email="jane@example.com", now=NOW)
    token = mail.sent[0].body.split("token=")[1]
    with pytest.raises(PasswordPolicyError):
        users.complete_reset(db, FAST, token=token, password="short", now=NOW)
    users.request_reset(db, mail, URL, email="jane@example.com", now=NOW)
    token = mail.sent[1].body.split("token=")[1]
    assert (
        users.complete_reset(db, FAST, token=token, password="amber-meadow-kettle-77", now=NOW)
        == uid
    )
    assert sessions.lookup(db, token_s, NOW) is None  # an old session cannot survive a reset
    r = accounts.authenticate(
        db,
        FAST,
        RING,
        email="jane@example.com",
        password="amber-meadow-kettle-77",
        totp_code=None,
        ip=None,
        user_agent=None,
        now=NOW,
    )
    assert r.status == "ok"
    with pytest.raises(users.UserError, match="not valid"):
        users.complete_reset(db, FAST, token=token, password="amber-meadow-kettle-77", now=NOW)
    # a link for an account that was suspended in the meantime is dead too
    users.request_reset(db, mail, URL, email="jane@example.com", now=NOW + timedelta(minutes=1))
    db.execute("UPDATE portal_user SET status='SUSPENDED' WHERE user_id=%s", (uid,))
    with pytest.raises(users.UserError, match="not valid"):
        users.complete_reset(
            db,
            FAST,
            token=mail.sent[2].body.split("token=")[1],
            password="another-long-passphrase-9",
            now=NOW,
        )


def test_an_admin_can_send_a_reset_link_only_to_an_active_account(db):
    boss, mail = make(db, "boss@example.com", "ADMIN"), ConsoleMailer()
    uid = make(db, "jane@example.com")
    url = users.admin_reset_password(db, mail, URL, actor=boss, user_id=uid, now=NOW)
    assert (
        url.startswith("https://portal.example/reset-password?token=")
        and mail.sent[0].to == "jane@example.com"
    )
    db.execute("UPDATE portal_user SET status='SUSPENDED' WHERE user_id=%s", (uid,))
    with pytest.raises(users.UserError, match="active account") as e:
        users.admin_reset_password(db, mail, URL, actor=boss, user_id=uid, now=NOW)
    assert e.value.status == 409
    with pytest.raises(users.UserError):
        users.admin_reset_password(db, mail, URL, actor=boss, user_id=uuid4(), now=NOW)


def test_role_changes_end_sessions_and_never_touch_yourself_or_the_last_admin(db):
    boss, other_admin, jane = (
        make(db, "boss@example.com", "ADMIN"),
        make(db, "two@example.com", "ADMIN"),
        make(db, "jane@example.com"),
    )
    s, _ = sessions.create(db, jane, now=NOW, mfa_verified=False, ip=None, user_agent=None)
    users.set_role(db, actor=boss, user_id=jane, role="OPERATOR", now=NOW)
    assert db.execute("SELECT role FROM portal_user WHERE user_id=%s", (jane,)).fetchone() == (
        "OPERATOR",
    )
    assert sessions.lookup(db, s, NOW) is None  # the new permissions apply from a fresh sign-in
    users.set_role(
        db, actor=boss, user_id=jane, role="OPERATOR", now=NOW
    )  # no change: no second audit entry
    assert len(audit.recent(db, action_prefix="user.role_changed")) == 1
    with pytest.raises(users.UserError, match="own role") as e:
        users.set_role(db, actor=boss, user_id=boss, role="VIEWER", now=NOW)
    assert e.value.status == 409
    users.set_role(
        db, actor=boss, user_id=other_admin, role="TRADER", now=NOW
    )  # fine: boss is still an admin
    with pytest.raises(users.UserError, match="last active administrator"):
        users.set_role(db, actor=jane, user_id=boss, role="TRADER", now=NOW)  # only boss is left
    with pytest.raises(users.UserError, match="unknown role"):
        users.set_role(db, actor=boss, user_id=jane, role="ROOT", now=NOW)
    with pytest.raises(users.UserError) as e2:
        users.set_role(db, actor=boss, user_id=uuid4(), role="VIEWER", now=NOW)
    assert e2.value.status == 404
    users.set_role(
        db, actor=boss, user_id=jane, role="ADMIN", now=NOW
    )  # promoting is always allowed
    assert db.execute("SELECT role FROM portal_user WHERE user_id=%s", (jane,)).fetchone() == (
        "ADMIN",
    )


def test_status_changes_end_sessions_and_never_lock_out_the_last_admin(db):
    boss, jane = make(db, "boss@example.com", "ADMIN"), make(db, "jane@example.com")
    s, _ = sessions.create(db, jane, now=NOW, mfa_verified=False, ip=None, user_agent=None)
    users.set_status(db, actor=boss, user_id=jane, status="SUSPENDED", now=NOW)
    assert sessions.lookup(db, s, NOW) is None
    users.set_status(
        db, actor=boss, user_id=jane, status="SUSPENDED", now=NOW
    )  # already so: nothing recorded twice
    assert len(audit.recent(db, action_prefix="user.status_changed")) == 1
    users.set_status(db, actor=boss, user_id=jane, status="ACTIVE", now=NOW)
    pending, _ = users.invite(
        db,
        FAST,
        ConsoleMailer(),
        URL,
        actor=boss,
        email="p@example.com",
        name="Pend Ing",
        role="VIEWER",
        now=NOW,
    )
    with pytest.raises(users.UserError, match="not accepted") as e:
        users.set_status(db, actor=boss, user_id=pending, status="ACTIVE", now=NOW)
    assert e.value.status == 409
    with pytest.raises(users.UserError, match="own status"):
        users.set_status(db, actor=boss, user_id=boss, status="DISABLED", now=NOW)
    users.set_role(db, actor=boss, user_id=jane, role="ADMIN", now=NOW)
    users.set_status(
        db, actor=jane, user_id=boss, status="DISABLED", now=NOW
    )  # jane is another active admin: allowed
    with pytest.raises(users.UserError, match="last active administrator"):
        users.set_status(
            db, actor=pending, user_id=jane, status="DISABLED", now=NOW
        )  # jane is the only one left
    with pytest.raises(users.UserError, match="status must be"):
        users.set_status(db, actor=jane, user_id=boss, status="INVITED", now=NOW)
    with pytest.raises(users.UserError) as e2:
        users.set_status(db, actor=jane, user_id=uuid4(), status="ACTIVE", now=NOW)
    assert e2.value.status == 404


def test_renaming_and_ending_sessions(db):
    boss, jane = make(db, "boss@example.com", "ADMIN"), make(db, "jane@example.com")
    users.rename(db, actor=boss, user_id=jane, name="  Jane Q. Roe ", now=NOW)
    assert db.execute(
        "SELECT display_name FROM portal_user WHERE user_id=%s", (jane,)
    ).fetchone() == ("Jane Q. Roe",)
    for bad in ("", "   ", "x" * 121):
        with pytest.raises(users.UserError):
            users.rename(db, actor=boss, user_id=jane, name=bad, now=NOW)
    with pytest.raises(users.UserError):
        users.rename(db, actor=boss, user_id=uuid4(), name="X", now=NOW)
    sessions.create(db, jane, now=NOW, mfa_verified=False, ip=None, user_agent=None)
    sessions.create(db, jane, now=NOW, mfa_verified=False, ip=None, user_agent=None)
    assert users.end_sessions(db, actor=boss, user_id=jane, now=NOW) == 2
    with pytest.raises(users.UserError):
        users.end_sessions(db, actor=boss, user_id=uuid4(), now=NOW)


def test_resetting_a_lost_second_factor_clears_it_and_signs_the_user_out(db):
    boss, jane = make(db, "boss@example.com", "ADMIN"), make(db, "jane@example.com", "OPERATOR")
    secret, _ = accounts.begin_mfa_enrolment(db, RING, user_id=jane)
    accounts.confirm_mfa(
        db, RING, user_id=jane, code=totp.code_at(secret, int(NOW.timestamp()) // 30), now=NOW
    )
    s, _ = sessions.create(db, jane, now=NOW, mfa_verified=True, ip=None, user_agent=None)
    assert users.get_user(db, jane, NOW)["recovery_codes_left"] == 10
    users.reset_mfa(db, actor=boss, user_id=jane, now=NOW)
    p = users.get_user(db, jane, NOW)
    assert (p["mfa_enabled"], p["recovery_codes_left"]) == (False, 0) and sessions.lookup(
        db, s, NOW
    ) is None
    assert accounts.needs_enrolment(
        "OPERATOR", p["mfa_enabled"]
    )  # an operator must enrol again at next sign-in
    with pytest.raises(users.UserError, match="own two-factor"):
        users.reset_mfa(db, actor=boss, user_id=boss, now=NOW)
    with pytest.raises(users.UserError):
        users.reset_mfa(db, actor=boss, user_id=uuid4(), now=NOW)
