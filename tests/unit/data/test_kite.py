import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest

from algo.data.providers.kite import (
    KiteClient,
    KiteError,
    KiteInputError,
    KiteTokenExpired,
    checksum,
    login_url,
    parse_candles,
    parse_instruments,
    windows,
)

IST = ZoneInfo("Asia/Kolkata")

INSTRUMENTS = (
    b"instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange\n"
    b'738561,2885,RELIANCE,"RELIANCE INDUSTRIES",0,,0,0.05,1,EQ,NSE,NSE\n'
    b"128083204,500325,RELIANCE,,0,,0,0.05,1,EQ,BSE,BSE\n"
    b"9999,39,NIFTY24DECFUT,NIFTY,0,2024-12-26,0,0.05,25,FUT,NFO-FUT,NFO\n"
    b"5633,22,ACC,ACC LIMITED,0,,0,0.05,1,EQ,NSE,NSE\n"
)

CANDLES = json.dumps(
    {"status": "success", "data": {"candles": [
        ["2024-12-02T09:15:00+0530", 2900.5, 2905, 2899.25, 2903.1, 12345],
        ["2024-12-02T09:16:00+0530", 2903.1, 2904, 2901, 2902, 800],
    ]}}
).encode()  # fmt: skip


def test_the_checksum_is_the_sha256_of_key_then_token_then_secret():
    assert checksum("KEY", "REQ", "SECRET") == hashlib.sha256(b"KEYREQSECRET").hexdigest()
    assert checksum("KEY", "REQ", "SECRET") != checksum("KEY", "SECRET", "REQ")  # order matters


def test_the_login_url_carries_the_version_and_the_api_key():
    assert login_url("abc123") == "https://kite.zerodha.com/connect/login?v=3&api_key=abc123"


def test_the_instrument_list_gives_nse_cash_equities_only_keyed_by_trading_symbol():
    ins = parse_instruments(INSTRUMENTS)
    assert sorted(i.tradingsymbol for i in ins) == [
        "ACC",
        "RELIANCE",
    ]  # BSE and futures rows are excluded
    rel = next(i for i in ins if i.tradingsymbol == "RELIANCE")
    assert (rel.instrument_token, rel.exchange_token, rel.name, rel.exchange, rel.segment) == (
        738561,
        2885,
        "RELIANCE INDUSTRIES",
        "NSE",
        "NSE",
    )


def test_a_malformed_instrument_list_is_refused():
    with pytest.raises(KiteError, match="instrument list"):
        parse_instruments(b"<html>maintenance</html>")


def test_candles_become_utc_timestamps_with_decimal_prices_never_floats():
    c = parse_candles(CANDLES)
    assert len(c) == 2 and c[0].ts == datetime(2024, 12, 2, 3, 45, tzinfo=UTC)  # 09:15 IST
    assert (c[0].open, c[0].high, c[0].low, c[0].close, c[0].volume) == (
        D("2900.5"),
        D("2905"),
        D("2899.25"),
        D("2903.1"),
        D(12345),
    )
    assert all(isinstance(x, D) for x in (c[0].open, c[0].close, c[0].volume))
    assert c[0].oi is None


def test_oi_is_read_when_present_and_an_empty_response_is_an_empty_list():
    with_oi = json.dumps(
        {
            "status": "success",
            "data": {"candles": [["2024-12-02T09:15:00+0530", 1, 2, 1, 2, 10, 55]]},
        }
    ).encode()
    assert parse_candles(with_oi)[0].oi == D(55)
    assert parse_candles(json.dumps({"status": "success", "data": {"candles": []}}).encode()) == []


@pytest.mark.parametrize(
    "raw",
    [b"not json", b'{"status": "error", "message": "x"}', b'{"status": "success", "data": {}}',
     json.dumps({"status": "success", "data": {"candles": [["2024-12-02T09:15:00+0530", 1, 2]]}}).encode()],
)  # fmt: skip
def test_unreadable_candle_responses_are_refused(raw):
    with pytest.raises(KiteError):
        parse_candles(raw)


def test_a_range_is_cut_into_contiguous_non_overlapping_windows_of_at_most_n_days():
    w = windows(date(2024, 1, 1), date(2024, 5, 29), 60)
    assert w[0][0] == date(2024, 1, 1) and w[-1][1] == date(2024, 5, 29)
    assert all((b - a).days + 1 <= 60 for a, b in w)
    assert all(
        w[i][1] + timedelta(days=1) == w[i + 1][0] for i in range(len(w) - 1)
    )  # the next window starts the day after
    assert windows(date(2024, 1, 1), date(2024, 1, 1), 60) == [(date(2024, 1, 1), date(2024, 1, 1))]
    assert windows(date(2024, 2, 1), date(2024, 1, 1), 60) == []


class Http:
    """An injected transport: records every call and returns the queued (status, body) answers."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, method, url, headers, data=None):
        self.calls.append((method, url, dict(headers), data))
        return self.answers.pop(0)


def client(http, sleeps=None, t=None):
    clock = iter(t or [0.0] * 100)
    return KiteClient(
        "KEY",
        "TOKEN",
        http,
        min_interval=0.4,
        retries=3,
        backoff=1.0,
        sleep=(sleeps.append if sleeps is not None else lambda s: None),
        clock=lambda: next(clock),
    )


def ok(body):
    return 200, body


def test_requests_are_signed_with_the_version_header_and_the_token_scheme():
    http = Http(ok(INSTRUMENTS))
    client(http).instruments("NSE")
    method, url, headers, _ = http.calls[0]
    assert (method, url) == ("GET", "https://api.kite.trade/instruments/NSE")
    assert headers["X-Kite-Version"] == "3" and headers["Authorization"] == "token KEY:TOKEN"


def test_the_historical_call_formats_the_range_as_the_documentation_requires():
    http = Http(ok(CANDLES))
    out = client(http).historical(
        738561,
        "minute",
        datetime(2024, 12, 2, 9, 15, tzinfo=IST),
        datetime(2024, 12, 2, 15, 30, tzinfo=IST),
    )
    assert len(out) == 2
    assert (
        http.calls[0][1]
        == "https://api.kite.trade/instruments/historical/738561/minute?from=2024-12-02+09%3A15%3A00&to=2024-12-02+15%3A30%3A00"
    )


def test_calls_are_spaced_by_the_minimum_interval():
    sleeps = []
    c = client(
        Http(ok(INSTRUMENTS), ok(INSTRUMENTS)), sleeps, t=[10.0, 10.1, 10.1, 10.1, 10.6, 10.6]
    )
    c.instruments("NSE")
    c.instruments("NSE")
    assert (
        sleeps and 0.29 < sleeps[0] <= 0.3 + 1e-9
    )  # the second call came 0.1s after the first: wait the remaining 0.3s


def test_an_expired_session_is_a_distinct_error_and_is_never_retried():
    http = Http(
        (
            403,
            b'{"status": "error", "message": "Incorrect api_key or access_token", "error_type": "TokenException"}',
        )
    )
    with pytest.raises(KiteTokenExpired):
        client(http).instruments("NSE")
    assert len(http.calls) == 1


def test_bad_input_is_reported_with_the_servers_message_and_not_retried():
    http = Http(
        (
            400,
            b'{"status": "error", "message": "interval exceeds max limit: 60 days", "error_type": "InputException"}',
        )
    )
    with pytest.raises(KiteInputError, match="exceeds max limit: 60 days"):
        client(http).historical(
            1, "minute", datetime(2020, 1, 1, tzinfo=IST), datetime(2024, 1, 1, tzinfo=IST)
        )
    assert len(http.calls) == 1


def test_rate_limiting_and_server_errors_are_retried_with_growing_waits_then_succeed():
    sleeps = []
    http = Http(
        (
            429,
            b'{"status": "error", "message": "Too many requests", "error_type": "NetworkException"}',
        ),
        (503, b""),
        ok(INSTRUMENTS),
    )
    assert len(client(http, sleeps).instruments("NSE")) == 2
    assert len(http.calls) == 3 and [x for x in sleeps if x >= 1.0] == [
        1.0,
        2.0,
    ]  # retry waits 1s then 2s (throttle waits are shorter)


def test_persistent_failure_ends_in_a_clear_error_after_the_retries():
    http = Http(*[(500, b"boom")] * 4)
    with pytest.raises(KiteError, match="HTTP 500"):
        client(http).instruments("NSE")
    assert len(http.calls) == 4  # the first try plus three retries


def test_the_session_exchange_posts_the_checksum_and_returns_the_access_token():
    http = Http(
        ok(
            json.dumps(
                {"status": "success", "data": {"access_token": "AT123", "user_id": "KL2138"}}
            ).encode()
        )
    )
    out = KiteClient.exchange_token("KEY", "SECRET", "REQ", http)
    method, url, headers, data = http.calls[0]
    assert (method, url, out) == (
        "POST",
        "https://api.kite.trade/session/token",
        ("AT123", "KL2138"),
    )
    assert data == {
        "api_key": "KEY",
        "request_token": "REQ",
        "checksum": hashlib.sha256(b"KEYREQSECRET").hexdigest(),
    }
    assert (
        headers["X-Kite-Version"] == "3" and "Authorization" not in headers
    )  # no token exists yet
    with pytest.raises(KiteError, match="token exchange"):
        KiteClient.exchange_token(
            "KEY", "SECRET", "REQ", Http((200, b'{"status": "error", "message": "bad"}'))
        )


def test_no_wait_is_added_when_the_previous_call_was_long_enough_ago():
    sleeps = []
    c = client(Http(ok(INSTRUMENTS), ok(INSTRUMENTS)), sleeps, t=[10.0, 11.0, 11.0, 11.0])
    c.instruments("NSE")
    c.instruments("NSE")  # a full second later: the 0.4s spacing is already satisfied
    assert sleeps == []


def test_the_untouched_response_bytes_can_be_captured_for_the_archive():
    seen: list[bytes] = []
    c = client(lambda m, u, h, d=None: (200, CANDLES))
    c.historical(
        738561,
        "minute",
        datetime(2024, 12, 2, tzinfo=IST),
        datetime(2024, 12, 3, tzinfo=IST),
        raw_sink=seen.append,
    )
    c2 = client(lambda m, u, h, d=None: (200, INSTRUMENTS))
    c2.instruments("NSE", raw_sink=seen.append)
    assert seen == [CANDLES, INSTRUMENTS]  # exactly as received, before any parsing
