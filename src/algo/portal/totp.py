# ruff: noqa: E501
"""TOTP second factor (RFC 6238: HMAC-SHA1, 30 s steps, 6 digits) and single-use recovery codes. The clock is passed in."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from datetime import datetime
from urllib.parse import quote

STEP_SECONDS = 30
DIGITS = 6
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no look-alikes (i l o 0 1)


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode()


def code_at(secret: str, step: int) -> str:
    key = base64.b32decode(secret)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()  # noqa: S324 (the RFC's algorithm)
    offset = digest[-1] & 0x0F
    value = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 10**DIGITS
    return f"{value:0{DIGITS}d}"


def verify(
    secret: str, code: str, now: datetime, *, last_step: int | None, window: int = 1
) -> int | None:
    """The matching step, or None. One step of clock drift either way is tolerated; a step at or before `last_step`
    (the last accepted one) is refused, so a code cannot be used twice."""
    if len(code) != DIGITS or not code.isascii() or not code.isdigit():
        return None
    current = int(now.timestamp()) // STEP_SECONDS
    for step in range(current - window, current + window + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def provisioning_uri(secret: str, account: str, issuer: str) -> str:
    return (
        f"otpauth://totp/{quote(issuer)}:{quote(account, safe='')}?secret={secret}"
        f"&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"
    )


def new_recovery_codes(count: int = 10) -> list[str]:
    out: set[str] = set()
    while len(out) < count:
        out.add("".join(secrets.choice(ALPHABET) for _ in range(10)))
    return [f"{c[:5]}-{c[5:]}" for c in sorted(out)]


def hash_recovery(code: str) -> str:
    norm = "".join(ch for ch in code.lower() if ch.isalnum())
    return hashlib.sha256(norm.encode()).hexdigest()
