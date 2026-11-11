import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from algo.data.store.migrate import migrate
from algo.portal import accounts, audit, kite_vault
from tests.support.portal import FAST, RING

pytestmark = pytest.mark.integration
NOW = datetime(
    2026, 11, 11, 10, 0, tzinfo=UTC
)  # 15:30 IST: the token will expire at 06:00 IST the next day
KEY, SECRET = "abcd1234efgh5678", "zyxw9876vuts5432"
URL = "https://portal.example"


@pytest.fixture
def db(conn):
    migrate(conn)
    return conn


def person(db, email, role="TRADER"):
    return accounts.create_user(
        db,
        FAST,
        email=email,
        display_name="Test User",
        role=role,
        password="violet-harbor-lantern-42",
        now=NOW,
    )


def kite_ok(token="ACCESS-TOKEN-1", user="AB1234"):
    calls = []

    def http(method, url, headers, data=None):
        calls.append((method, url, dict(data or {})))
        return 200, json.dumps(
            {"status": "success", "data": {"access_token": token, "user_id": user}}
        ).encode()

    http.calls = calls
    return http


def kite_refuses(message="Token is invalid or has expired."):
    return lambda method, url, headers, data=None: (
        403,
        json.dumps(
            {"status": "error", "message": message, "error_type": "TokenException"}
        ).encode(),
    )


def configured(db, email="jane@example.com"):
    uid = person(db, email)
    kite_vault.save_credentials(db, RING, user_id=uid, api_key=KEY, api_secret=SECRET, now=NOW)
    return uid


def state_of(login_url):
    return unquote(parse_qs(urlparse(login_url).query)["redirect_params"][0]).removeprefix("state=")


def test_credentials_are_validated_stored_only_encrypted_and_shown_as_a_hint(db):
    uid = person(db, "jane@example.com")
    assert (
        kite_vault.get_connection(db, user_id=uid, now=NOW, public_url=URL)["state"]
        == "not_configured"
    )
    for bad in (
        dict(api_key="short", api_secret=SECRET),
        dict(api_key=KEY, api_secret="has space!!!!"),
        dict(api_key="x" * 65, api_secret=SECRET),
    ):
        with pytest.raises(kite_vault.KiteVaultError):
            kite_vault.save_credentials(db, RING, user_id=uid, now=NOW, **bad)
    kite_vault.save_credentials(
        db, RING, user_id=uid, api_key=f"  {KEY} ", api_secret=SECRET, now=NOW
    )
    stored = " ".join(
        str(v)
        for v in db.execute(
            "SELECT api_key_enc, api_secret_enc FROM portal_kite_connection"
        ).fetchone()
    )
    assert KEY not in stored and SECRET not in stored
    c = kite_vault.get_connection(db, user_id=uid, now=NOW, public_url=URL + "/")
    assert (c["state"], c["api_key_hint"], c["redirect_url"], c["is_system"]) == (
        "saved",
        "5678",
        "https://portal.example/kite/callback",
        False,
    )
    assert KEY not in json.dumps(c, default=str) and SECRET not in json.dumps(c, default=str)
    assert "5678" in str(
        audit.recent(db, action_prefix="kite.credentials_saved", limit=1)[0]["detail"]
    ) and KEY not in str(audit.recent(db, limit=5))


def test_connecting_goes_through_kite_with_a_one_time_state_and_stores_only_an_encrypted_token(db):
    uid = configured(db)
    login = kite_vault.begin_connect(db, RING, user_id=uid, now=NOW)
    assert login.startswith(
        f"https://kite.zerodha.com/connect/login?v=3&api_key={KEY}&redirect_params="
    )
    state = state_of(login)
    http = kite_ok()
    assert (
        kite_vault.complete_connect(
            db,
            RING,
            http,
            user_id=uid,
            request_token="REQ1",
            state=state,
            now=NOW + timedelta(minutes=2),
        )
        == "AB1234"
    )
    assert (
        http.calls[0][1].endswith("/session/token")
        and http.calls[0][2]["request_token"] == "REQ1"
        and SECRET not in str(http.calls[0][2])
    )  # the secret only enters the checksum
    stored = " ".join(
        str(v) for v in db.execute("SELECT access_token_enc FROM portal_kite_connection").fetchone()
    )
    assert "ACCESS-TOKEN-1" not in stored
    later = NOW + timedelta(minutes=2)
    c = kite_vault.get_connection(db, user_id=uid, now=later, public_url=URL)
    assert (c["state"], c["kite_user_id"]) == ("connected", "AB1234") and c[
        "token_expires_at"
    ] == datetime(2026, 11, 12, 0, 30, tzinfo=UTC)  # 06:00 IST
    assert (
        kite_vault.get_connection(
            db, user_id=uid, now=c["token_expires_at"] + timedelta(seconds=1), public_url=URL
        )["state"]
        == "expired"
    )
    with pytest.raises(kite_vault.KiteVaultError, match="not valid any more"):
        kite_vault.complete_connect(
            db, RING, http, user_id=uid, request_token="REQ1", state=state, now=later
        )  # the state is spent
    assert audit.recent(db, action_prefix="kite.connected", limit=1)[0]["detail"] == {
        "kite_user": "AB1234"
    }


def test_a_login_cannot_be_completed_by_another_user_after_the_time_limit_or_with_a_guessed_state(
    db,
):
    jane, bob = configured(db, "jane@example.com"), configured(db, "bob@example.com")
    state = state_of(kite_vault.begin_connect(db, RING, user_id=jane, now=NOW))
    for who, st, when in (
        (bob, state, NOW),
        (jane, "guessed", NOW),
        (jane, state, NOW + kite_vault.STATE_TTL + timedelta(seconds=1)),
    ):
        with pytest.raises(kite_vault.KiteVaultError, match="not valid any more"):
            kite_vault.complete_connect(
                db, RING, kite_ok(), user_id=who, request_token="R", state=st, now=when
            )
    assert (
        kite_vault.complete_connect(
            db, RING, kite_ok(), user_id=jane, request_token="R", state=state, now=NOW
        )
        == "AB1234"
    )  # still good for the right user


def test_when_kite_refuses_the_failure_is_recorded_and_nothing_is_stored(db):
    uid = configured(db)
    state = state_of(kite_vault.begin_connect(db, RING, user_id=uid, now=NOW))
    with pytest.raises(kite_vault.KiteVaultError, match="Kite refused the login"):
        kite_vault.complete_connect(
            db, RING, kite_refuses(), user_id=uid, request_token="R", state=state, now=NOW
        )
    assert kite_vault.get_connection(db, user_id=uid, now=NOW, public_url=URL)["state"] == "saved"
    assert "kite.connect_failed" in [e["action"] for e in audit.recent(db)]


def test_connecting_without_saved_or_readable_credentials_is_refused(db):
    uid = person(db, "jane@example.com")
    with pytest.raises(kite_vault.KiteVaultError) as e:
        kite_vault.begin_connect(db, RING, user_id=uid, now=NOW)
    assert e.value.status == 409
    kite_vault.save_credentials(db, RING, user_id=uid, api_key=KEY, api_secret=SECRET, now=NOW)
    db.execute("UPDATE portal_kite_connection SET api_secret_enc='v1.AAAA'")
    with pytest.raises(kite_vault.KiteVaultError, match="cannot be read"):
        kite_vault.begin_connect(db, RING, user_id=uid, now=NOW)


def test_saving_again_replaces_the_credentials_and_forgets_the_old_connection_disconnect_and_remove_work(
    db,
):
    uid = configured(db)
    state = state_of(kite_vault.begin_connect(db, RING, user_id=uid, now=NOW))
    kite_vault.complete_connect(
        db, RING, kite_ok(), user_id=uid, request_token="R", state=state, now=NOW
    )
    kite_vault.save_credentials(
        db, RING, user_id=uid, api_key="newkey123456", api_secret=SECRET, now=NOW
    )
    assert kite_vault.get_connection(db, user_id=uid, now=NOW, public_url=URL)["state"] == "saved"
    state = state_of(kite_vault.begin_connect(db, RING, user_id=uid, now=NOW))
    kite_vault.complete_connect(
        db, RING, kite_ok(), user_id=uid, request_token="R", state=state, now=NOW
    )
    kite_vault.disconnect(db, user_id=uid, now=NOW)
    assert (
        kite_vault.get_connection(db, user_id=uid, now=NOW, public_url=URL)["state"] == "saved"
    )  # credentials stay
    assert kite_vault.remove_credentials(db, user_id=uid, now=NOW) is True
    assert kite_vault.remove_credentials(db, user_id=uid, now=NOW) is False
    assert (
        kite_vault.get_connection(db, user_id=uid, now=NOW, public_url=URL)["state"]
        == "not_configured"
    )


def test_one_connection_can_be_the_system_feed_and_the_loaders_get_its_credentials_only_while_the_token_is_valid(
    db,
):
    boss, other = configured(db, "boss@example.com"), configured(db, "other@example.com")
    assert (
        kite_vault.system_feed(db, now=NOW) is None
        and kite_vault.system_feed_credentials(db, RING, now=NOW) is None
    )
    with pytest.raises(kite_vault.KiteVaultError):
        kite_vault.set_system_feed(
            db, actor=boss, user_id=person(db, "none@example.com"), enabled=True, now=NOW
        )  # nothing saved
    kite_vault.set_system_feed(db, actor=boss, user_id=boss, enabled=True, now=NOW)
    assert (
        kite_vault.system_feed(db, now=NOW)["state"] == "saved"
        and kite_vault.system_feed_credentials(db, RING, now=NOW) is None
    )  # no token yet
    state = state_of(kite_vault.begin_connect(db, RING, user_id=boss, now=NOW))
    kite_vault.complete_connect(
        db, RING, kite_ok(token="FEED-TOKEN"), user_id=boss, request_token="R", state=state, now=NOW
    )
    assert kite_vault.system_feed_credentials(db, RING, now=NOW) == (KEY, "FEED-TOKEN")
    feed = kite_vault.system_feed(db, now=NOW)
    assert (feed["owner"], feed["state"], feed["api_key_hint"]) == (
        "Test User",
        "connected",
        "5678",
    )
    assert kite_vault.system_feed(db, now=NOW + timedelta(days=1))["state"] == "expired"
    assert kite_vault.system_feed_credentials(db, RING, now=NOW + timedelta(days=1)) is None
    kite_vault.set_system_feed(
        db, actor=boss, user_id=other, enabled=True, now=NOW
    )  # moving the mark clears the old holder
    assert db.execute("SELECT user_id FROM portal_kite_connection WHERE is_system").fetchall() == [
        (other,)
    ]
    kite_vault.set_system_feed(db, actor=boss, user_id=other, enabled=False, now=NOW)
    assert kite_vault.system_feed(db, now=NOW) is None
    assert {e["action"] for e in audit.recent(db, action_prefix="kite.system_feed")} == {
        "kite.system_feed_set",
        "kite.system_feed_cleared",
    }
