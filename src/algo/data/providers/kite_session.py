# ruff: noqa: E501  (docstrings are kept readable)
"""Kite session plumbing: the .env keys, the daily access token on disk, the pasted redirect, and the real HTTP transport.

The access token is a secret: it is written owner-only (0600 in a 0700 directory), never printed, and treated as
expired from 6 AM IST the next day (Kite invalidates tokens then; there is no automated refresh by design)."""

from __future__ import annotations

import http.client
import json
import os
import re
import urllib.error
import urllib.request
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def expires_at(issued: datetime) -> datetime:
    """The next 6 AM IST strictly after `issued`."""
    local = issued.astimezone(IST)
    six = datetime.combine(local.date(), time(6, 0), IST)
    if local >= six:
        six += timedelta(days=1)
    return six.astimezone(UTC)


def load_env(path: Path) -> dict[str, str]:
    """KEY=VALUE lines; comments, blanks and lines without '=' are ignored; one pair of quotes is stripped."""
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def save_token(path: Path, access_token: str, user_id: str, issued: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    doc = {
        "access_token": access_token,
        "user_id": user_id,
        "issued_at": issued.astimezone(UTC).isoformat(),
        "expires_at": expires_at(issued).isoformat(),
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(doc))
    os.chmod(path, 0o600)


def load_token(path: Path, now: datetime) -> tuple[str, str] | None:
    """(access_token, user_id) while the session is valid; None when absent, unreadable or expired."""
    try:
        doc = json.loads(path.read_text())
        if now >= datetime.fromisoformat(doc["expires_at"]):
            return None
        return str(doc["access_token"]), str(doc["user_id"])
    except (OSError, ValueError, KeyError):
        return None


def request_token_from(pasted: str) -> str:
    """The request_token from the pasted redirect URL (or the bare token). A failed login is refused."""
    s = pasted.strip()
    if not s:
        raise ValueError("nothing pasted: expected the redirect URL or the request_token")
    if "://" in s or "?" in s:
        qs = parse_qs(urlparse(s).query)
        if qs.get("status") == ["error"]:
            raise ValueError("the login did not succeed, so no request_token was issued")
        token = qs.get("request_token")
        if not token:
            raise ValueError("no request_token in the pasted URL")
        return token[0]
    if not re.fullmatch(r"[A-Za-z0-9]+", s):
        raise ValueError("that is not a request_token (letters and digits only)")
    return s


def urllib_http(
    method: str,
    url: str,
    headers: dict[str, str],
    data: dict[str, str] | None = None,
    *,
    opener: Any = None,
    timeout: float = 60.0,
) -> tuple[int, bytes]:
    """The real transport: (status, body). HTTP errors are returned, a network failure is status 0."""
    body = urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)  # noqa: S310
    op = opener or urllib.request.build_opener()
    try:
        with op.open(req, timeout=timeout) as r:
            return int(r.status), bytes(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except urllib.error.URLError as e:
        return 0, repr(e.reason).encode()
    except (
        OSError,
        http.client.HTTPException,
    ) as e:  # a timeout, reset or truncated body while reading (not wrapped in URLError)
        return 0, (str(e) or repr(e)).encode()
