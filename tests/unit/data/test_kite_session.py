import io
import json
import stat
import urllib.error
from datetime import UTC, datetime

import pytest
from algo.data.providers.kite_session import (
    expires_at,
    load_env,
    load_token,
    request_token_from,
    save_token,
    urllib_http,
)


def utc(*a):
    return datetime(*a, tzinfo=UTC)


def test_a_token_issued_before_6am_ist_expires_at_6am_that_day_and_after_6am_the_next_day():
    # 6 AM IST = 00:30 UTC
    assert expires_at(utc(2026, 11, 10, 0, 10)) == utc(
        2026, 11, 10, 0, 30
    )  # 05:40 IST: this morning's 6 AM
    assert expires_at(utc(2026, 11, 10, 0, 30)) == utc(
        2026, 11, 11, 0, 30
    )  # exactly 6 AM: the next one
    assert expires_at(utc(2026, 11, 10, 10, 0)) == utc(
        2026, 11, 11, 0, 30
    )  # 15:30 IST: tomorrow 6 AM


def test_env_lines_are_parsed_with_comments_quotes_and_blank_lines_ignored(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# secrets\n\nA=1\nB=\"two words\"\nC='x'\nD=has=equals\nnot a pair\nE=\n")
    assert load_env(p) == {"A": "1", "B": "two words", "C": "x", "D": "has=equals", "E": ""}
    assert load_env(tmp_path / "missing") == {}


def test_the_token_file_is_private_roundtrips_and_is_never_returned_once_expired(tmp_path):
    p = tmp_path / "secrets" / "kite_token.json"
    issued = utc(2026, 11, 10, 3, 0)
    save_token(p, "AT123", "KL2138", issued)
    assert (
        stat.S_IMODE(p.stat().st_mode) == 0o600 and stat.S_IMODE(p.parent.stat().st_mode) == 0o700
    )
    assert json.loads(p.read_text())["expires_at"] == "2026-11-11T00:30:00+00:00"
    assert load_token(p, utc(2026, 11, 10, 20, 0)) == (
        "AT123",
        "KL2138",
    )  # still valid that evening
    assert load_token(p, utc(2026, 11, 11, 0, 30)) is None  # expired at 6 AM
    assert load_token(tmp_path / "nothing.json", issued) is None
    p.write_text("{not json")
    assert load_token(p, issued) is None  # an unreadable file is treated as no session, not a crash


@pytest.mark.parametrize(
    ("pasted", "token"),
    [
        (
            "http://127.0.0.1:5000/callback?action=login&type=login&status=success&request_token=abcDEF123",
            "abcDEF123",
        ),
        ("https://example.com/cb?request_token=zzz&action=login&status=success", "zzz"),
        ("abcDEF123", "abcDEF123"),  # the bare token is accepted too
        ("  abcDEF123\n", "abcDEF123"),
    ],
)
def test_the_request_token_is_taken_from_the_pasted_redirect_url_or_the_bare_token(pasted, token):
    assert request_token_from(pasted) == token


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "http://127.0.0.1:5000/callback?status=error&message=denied",
        "http://x/cb?status=success",
        "two words",
    ],
)
def test_a_failed_or_tokenless_redirect_is_refused(bad):
    with pytest.raises(ValueError, match="request_token"):
        request_token_from(bad)


class Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Opener:
    def __init__(self, result):
        self.result, self.requests = result, []

    def open(self, req, timeout=None):
        self.requests.append(req)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_the_real_transport_posts_form_data_and_returns_status_and_body():
    op = Opener(Resp(b'{"ok": 1}'))
    status, body = urllib_http(
        "POST",
        "https://api.kite.trade/session/token",
        {"X-Kite-Version": "3"},
        {"a": "1"},
        opener=op,
    )
    req = op.requests[0]
    assert (
        (status, body) == (200, b'{"ok": 1}') and req.get_method() == "POST" and req.data == b"a=1"
    )
    assert req.get_header("X-kite-version") == "3"


def test_an_http_error_is_returned_as_its_status_and_body_not_raised():
    err = urllib.error.HTTPError(
        "u", 403, "Forbidden", {}, io.BytesIO(b'{"error_type": "TokenException"}')
    )  # type: ignore[arg-type]
    status, body = urllib_http("GET", "https://api.kite.trade/x", {}, opener=Opener(err))
    assert (status, body) == (403, b'{"error_type": "TokenException"}')
    status, body = urllib_http(
        "GET", "https://api.kite.trade/x", {}, opener=Opener(urllib.error.URLError("down"))
    )
    assert (
        status == 0 and b"down" in body
    )  # a network failure is a status 0 the client treats as an error
