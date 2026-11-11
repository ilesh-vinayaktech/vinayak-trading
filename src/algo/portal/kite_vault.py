# ruff: noqa: E501
"""Per-user Kite Connect credentials and the daily connection flow.

Nothing secret ever leaves this module in a response: the API key shows only as a four-character hint, and the secret and
tokens are decrypted solely to talk to Kite. Connecting uses a one-time `state` bound to the user (sent to Kite as a
redirect parameter and checked when it comes back), so a login cannot be completed by someone else's browser."""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote
from uuid import UUID

import psycopg

from algo.data.providers.kite import KiteClient, KiteError, login_url
from algo.data.providers.kite_session import expires_at
from algo.portal import audit
from algo.portal.crypto import KeyRing, VaultError
from algo.portal.sessions import digest

Http = Callable[..., tuple[int, bytes]]
STATE_TTL = timedelta(minutes=10)
KEY_PATTERN = re.compile(r"^[A-Za-z0-9]{6,64}$")
CALLBACK_PATH = "/kite/callback"


class KiteVaultError(Exception):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def _aad(user_id: UUID, field: str) -> str:
    return f"user:{user_id}:kite_{field}"


def save_credentials(
    conn: psycopg.Connection,
    ring: KeyRing,
    *,
    user_id: UUID,
    api_key: str,
    api_secret: str,
    now: datetime,
) -> None:
    key, secret = api_key.strip(), api_secret.strip()
    if not KEY_PATTERN.match(key):
        raise KiteVaultError(
            "the API key should be letters and digits only (copy it from your Kite Connect app)"
        )
    if not KEY_PATTERN.match(secret):
        raise KiteVaultError(
            "the API secret should be letters and digits only (copy it from your Kite Connect app)"
        )
    conn.execute(
        "INSERT INTO portal_kite_connection (user_id, api_key_enc, api_secret_enc, api_key_hint, created_at, updated_at)"
        " VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (user_id) DO UPDATE SET api_key_enc=EXCLUDED.api_key_enc,"
        " api_secret_enc=EXCLUDED.api_secret_enc, api_key_hint=EXCLUDED.api_key_hint, access_token_enc=NULL, kite_user_id=NULL,"
        " connected_at=NULL, token_expires_at=NULL, connect_state_hash=NULL, connect_state_expires=NULL, updated_at=EXCLUDED.updated_at",
        (
            user_id,
            ring.encrypt(key, aad=_aad(user_id, "api_key")),
            ring.encrypt(secret, aad=_aad(user_id, "api_secret")),
            key[-4:],
            now,
            now,
        ),
    )
    audit.record(
        conn,
        now=now,
        action="kite.credentials_saved",
        actor_user_id=user_id,
        target_type="kite",
        target_id=str(user_id),
        detail={"key_hint": key[-4:]},
    )


def remove_credentials(conn: psycopg.Connection, *, user_id: UUID, now: datetime) -> bool:
    gone = (
        conn.execute("DELETE FROM portal_kite_connection WHERE user_id=%s", (user_id,)).rowcount > 0
    )
    if gone:
        audit.record(
            conn,
            now=now,
            action="kite.credentials_removed",
            actor_user_id=user_id,
            target_type="kite",
            target_id=str(user_id),
        )
    return gone


def get_connection(
    conn: psycopg.Connection, *, user_id: UUID, now: datetime, public_url: str
) -> dict[str, Any]:
    """What the screen needs; never a secret. `state`: not_configured | saved | connected | expired."""
    row = conn.execute(
        "SELECT api_key_hint, kite_user_id, connected_at, token_expires_at, is_system, access_token_enc FROM portal_kite_connection WHERE user_id=%s",
        (user_id,),
    ).fetchone()
    out: dict[str, Any] = {"redirect_url": public_url.rstrip("/") + CALLBACK_PATH}
    if row is None:
        return {
            **out,
            "state": "not_configured",
            "api_key_hint": None,
            "kite_user_id": None,
            "connected_at": None,
            "token_expires_at": None,
            "is_system": False,
        }
    hint, kite_user, connected, expires, is_system, token = row
    state = (
        "saved"
        if token is None
        else ("connected" if expires is not None and expires > now else "expired")
    )
    return {
        **out,
        "state": state,
        "api_key_hint": hint,
        "kite_user_id": kite_user,
        "connected_at": connected,
        "token_expires_at": expires,
        "is_system": is_system,
    }


def _credentials(conn: psycopg.Connection, ring: KeyRing, user_id: UUID) -> tuple[str, str]:
    row = conn.execute(
        "SELECT api_key_enc, api_secret_enc FROM portal_kite_connection WHERE user_id=%s",
        (user_id,),
    ).fetchone()
    if row is None:
        raise KiteVaultError("save your Kite API key and secret first", 409)
    try:
        return ring.decrypt(row[0], aad=_aad(user_id, "api_key")).decode(), ring.decrypt(
            row[1], aad=_aad(user_id, "api_secret")
        ).decode()
    except VaultError as e:
        raise KiteVaultError("the stored credentials cannot be read: save them again", 409) from e


def begin_connect(conn: psycopg.Connection, ring: KeyRing, *, user_id: UUID, now: datetime) -> str:
    """The Kite login address for this user's app; `state` comes back to us untouched and proves who started it."""
    api_key, _ = _credentials(conn, ring, user_id)
    state = secrets.token_urlsafe(24)
    conn.execute(
        "UPDATE portal_kite_connection SET connect_state_hash=%s, connect_state_expires=%s WHERE user_id=%s",
        (digest(state), now + STATE_TTL, user_id),
    )
    return f"{login_url(api_key)}&redirect_params={quote('state=' + state, safe='')}"


def complete_connect(
    conn: psycopg.Connection,
    ring: KeyRing,
    http: Http,
    *,
    user_id: UUID,
    request_token: str,
    state: str,
    now: datetime,
) -> str:
    row = conn.execute(
        "UPDATE portal_kite_connection SET connect_state_hash=NULL, connect_state_expires=NULL WHERE user_id=%s AND connect_state_hash=%s AND connect_state_expires > %s RETURNING user_id",
        (user_id, digest(state), now),
    ).fetchone()
    if row is None:
        raise KiteVaultError(
            "this connection attempt is not valid any more: start again from the Kite page"
        )
    api_key, api_secret = _credentials(conn, ring, user_id)
    try:
        access_token, kite_user = KiteClient.exchange_token(
            api_key, api_secret, request_token, http
        )
    except KiteError as e:
        audit.record(
            conn,
            now=now,
            action="kite.connect_failed",
            actor_user_id=user_id,
            target_type="kite",
            target_id=str(user_id),
            detail={"reason": str(e)[:200]},
        )
        conn.commit()  # keep the record of the failure even though the caller now refuses the request
        raise KiteVaultError(f"Kite refused the login: {e}") from e
    conn.execute(
        "UPDATE portal_kite_connection SET access_token_enc=%s, kite_user_id=%s, connected_at=%s, token_expires_at=%s, updated_at=%s WHERE user_id=%s",
        (
            ring.encrypt(access_token, aad=_aad(user_id, "access_token")),
            kite_user,
            now,
            expires_at(now),
            now,
            user_id,
        ),
    )
    audit.record(
        conn,
        now=now,
        action="kite.connected",
        actor_user_id=user_id,
        target_type="kite",
        target_id=str(user_id),
        detail={"kite_user": kite_user},
    )
    return kite_user


def disconnect(conn: psycopg.Connection, *, user_id: UUID, now: datetime) -> None:
    conn.execute(
        "UPDATE portal_kite_connection SET access_token_enc=NULL, kite_user_id=NULL, connected_at=NULL, token_expires_at=NULL, updated_at=%s WHERE user_id=%s",
        (now, user_id),
    )
    audit.record(
        conn,
        now=now,
        action="kite.disconnected",
        actor_user_id=user_id,
        target_type="kite",
        target_id=str(user_id),
    )


def set_system_feed(
    conn: psycopg.Connection, *, actor: UUID, user_id: UUID, enabled: bool, now: datetime
) -> None:
    """Marks (or unmarks) one user's connection as the data feed the loaders use. Only one connection holds the mark."""
    if enabled:
        if (
            conn.execute(
                "SELECT 1 FROM portal_kite_connection WHERE user_id=%s", (user_id,)
            ).fetchone()
            is None
        ):
            raise KiteVaultError("save the Kite credentials first", 409)
        conn.execute(
            "UPDATE portal_kite_connection SET is_system=false WHERE is_system AND user_id <> %s",
            (user_id,),
        )
    conn.execute(
        "UPDATE portal_kite_connection SET is_system=%s WHERE user_id=%s", (enabled, user_id)
    )
    audit.record(
        conn,
        now=now,
        action="kite.system_feed_set" if enabled else "kite.system_feed_cleared",
        actor_user_id=actor,
        target_type="kite",
        target_id=str(user_id),
    )


def system_feed(conn: psycopg.Connection, *, now: datetime) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT c.user_id, u.display_name, c.api_key_hint, c.token_expires_at, c.access_token_enc FROM portal_kite_connection c JOIN portal_user u USING (user_id) WHERE c.is_system",
        (),
    ).fetchone()
    if row is None:
        return None
    state = (
        "saved"
        if row[4] is None
        else ("connected" if row[3] is not None and row[3] > now else "expired")
    )
    return {
        "owner_id": str(row[0]),
        "owner": row[1],
        "api_key_hint": row[2],
        "state": state,
        "token_expires_at": row[3],
    }


def system_feed_credentials(
    conn: psycopg.Connection, ring: KeyRing, *, now: datetime
) -> tuple[str, str] | None:
    """(api key, access token) of the system feed while its daily token is valid, for the data loaders; None otherwise."""
    row = conn.execute(
        "SELECT user_id, api_key_enc, access_token_enc, token_expires_at FROM portal_kite_connection WHERE is_system AND access_token_enc IS NOT NULL AND token_expires_at > %s",
        (now,),
    ).fetchone()
    if row is None:
        return None
    uid = UUID(str(row[0]))
    return ring.decrypt(row[1], aad=_aad(uid, "api_key")).decode(), ring.decrypt(
        row[2], aad=_aad(uid, "access_token")
    ).decode()
