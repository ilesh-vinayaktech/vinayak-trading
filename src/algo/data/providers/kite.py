# ruff: noqa: E501  (docstrings and one-line mappings are kept readable)
"""Zerodha Kite Connect v3: session exchange, the instrument list and historical candles.

No network code lives here: the caller injects `http(method, url, headers, data) -> (status, body)`, so everything is
testable. Rules enforced: prices and volumes are Decimal (never floats), timestamps become UTC, a 403/TokenException is
a distinct error that is never retried (the daily login must be redone), bad input is reported with the server's message
and not retried, and only 429 / 5xx are retried with growing waits. Calls are spaced (historical data allows 3 per second).
Historical ranges are timezone-aware datetimes; Kite wants exchange-local (IST) wall times and the client converts."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

BASE = "https://api.kite.trade"
LOGIN = "https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"
IST = ZoneInfo("Asia/Kolkata")

Http = Callable[..., tuple[int, bytes]]


class KiteError(Exception):
    pass


class KiteTokenExpired(KiteError):
    """403 / TokenException: the session is gone (tokens expire at ~6 AM daily). Log in again; never retry."""


class KiteInputError(KiteError):
    """400 / InputException: the request itself is wrong (the message says how)."""


@dataclass(frozen=True)
class KiteInstrument:
    instrument_token: int
    exchange_token: int
    tradingsymbol: str
    name: str
    exchange: str
    segment: str
    instrument_type: str


@dataclass(frozen=True)
class Candle:
    ts: datetime  # candle open, UTC
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    oi: Decimal | None


def checksum(api_key: str, request_token: str, api_secret: str) -> str:
    return hashlib.sha256((api_key + request_token + api_secret).encode()).hexdigest()


def login_url(api_key: str) -> str:
    return LOGIN.format(api_key=api_key)


def parse_instruments(raw: bytes) -> list[KiteInstrument]:
    """NSE cash equities only (EQ on the NSE segment). The dump has no ISIN; symbols map through our NSE aliases."""
    try:
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
        if not rows or "instrument_token" not in rows[0]:
            raise ValueError
        return [
            KiteInstrument(int(r["instrument_token"]), int(r["exchange_token"]), r["tradingsymbol"], r["name"], r["exchange"], r["segment"], r["instrument_type"])
            for r in rows
            if r["exchange"] == "NSE" and r["segment"] == "NSE" and r["instrument_type"] == "EQ"
        ]  # fmt: skip
    except (ValueError, KeyError, UnicodeDecodeError) as e:
        raise KiteError("not a Kite instrument list") from e


def _json(raw: bytes) -> dict[str, Any]:
    try:
        doc = json.loads(raw, parse_float=Decimal, parse_int=Decimal)
    except ValueError as e:
        raise KiteError("response is not JSON") from e
    if not isinstance(doc, dict) or doc.get("status") != "success":
        raise KiteError(
            f"Kite returned an error: {doc.get('message') if isinstance(doc, dict) else doc!r}"
        )
    return doc


def parse_candles(raw: bytes) -> list[Candle]:
    data = _json(raw).get("data")
    candles = data.get("candles") if isinstance(data, dict) else None
    if not isinstance(candles, list):
        raise KiteError("response has no candles list")
    out = []
    for c in candles:
        if len(c) not in (6, 7):
            raise KiteError(f"a candle has {len(c)} fields, expected 6 or 7")
        out.append(
            Candle(datetime.fromisoformat(c[0]).astimezone(UTC), c[1], c[2], c[3], c[4], c[5], c[6] if len(c) == 7 else None)
        )  # fmt: skip
    return out


def windows(start: date, end: date, max_days: int) -> list[tuple[date, date]]:
    """Contiguous, non-overlapping inclusive windows of at most max_days days covering start..end."""
    out = []
    cur = start
    while cur <= end:
        stop = min(cur + timedelta(days=max_days - 1), end)
        out.append((cur, stop))
        cur = stop + timedelta(days=1)
    return out


def _error_message(body: bytes) -> tuple[str, str]:
    try:
        doc = json.loads(body)
        return str(doc.get("message", "")), str(doc.get("error_type", ""))
    except (ValueError, AttributeError):
        return body[:120].decode("utf-8", "replace"), ""


class KiteClient:
    def __init__(
        self,
        api_key: str,
        access_token: str,
        http: Http,
        *,
        min_interval: float = 0.4,
        retries: int = 3,
        backoff: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.api_key, self.access_token, self._http = api_key, access_token, http
        self.min_interval, self.retries, self.backoff = min_interval, retries, backoff
        self._sleep, self._clock = sleep, clock
        self._last: float | None = None
        self._lock = (
            threading.Lock()
        )  # spacing is global across threads; the requests themselves overlap

    def _throttle(self) -> None:
        with self._lock:
            if self._last is not None:
                wait = self.min_interval - (self._clock() - self._last)
                if wait > 0:
                    self._sleep(wait)
            self._last = self._clock()

    def _headers(self) -> dict[str, str]:
        return {"X-Kite-Version": "3", "Authorization": f"token {self.api_key}:{self.access_token}"}

    def _request(self, url: str) -> bytes:
        for attempt in range(self.retries + 1):
            self._throttle()
            status, body = self._http("GET", url, self._headers())
            if status == 200:
                return body
            message, error_type = _error_message(body)
            if status == 403 or error_type == "TokenException":
                raise KiteTokenExpired(message or "session expired: log in again")
            if status == 400:
                raise KiteInputError(message)
            if status in (429, 500, 502, 503, 504) and attempt < self.retries:
                self._sleep(self.backoff * 2**attempt)
                continue
            raise KiteError(f"HTTP {status}: {message}")
        raise KiteError("unreachable")  # pragma: no cover

    def instruments(
        self, exchange: str, *, raw_sink: Callable[[bytes], None] | None = None
    ) -> list[KiteInstrument]:
        body = self._request(f"{BASE}/instruments/{exchange}")
        if raw_sink:
            raw_sink(body)  # the response exactly as received, for the archive
        return parse_instruments(body)

    def historical(
        self,
        instrument_token: int,
        interval: str,
        start: datetime,
        end: datetime,
        *,
        raw_sink: Callable[[bytes], None] | None = None,
    ) -> list[Candle]:
        def local(d: datetime) -> str:
            return d.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S")

        q = urlencode({"from": local(start), "to": local(end)})
        body = self._request(f"{BASE}/instruments/historical/{instrument_token}/{interval}?{q}")
        if raw_sink:
            raw_sink(body)
        return parse_candles(body)

    @staticmethod
    def exchange_token(
        api_key: str, api_secret: str, request_token: str, http: Http
    ) -> tuple[str, str]:
        """request_token -> (access_token, user_id). The token is valid until ~6 AM the next day."""
        data = {
            "api_key": api_key,
            "request_token": request_token,
            "checksum": checksum(api_key, request_token, api_secret),
        }
        status, body = http("POST", f"{BASE}/session/token", {"X-Kite-Version": "3"}, data)
        try:
            doc = _json(body)
            return str(doc["data"]["access_token"]), str(doc["data"]["user_id"])
        except (KiteError, KeyError, TypeError) as e:
            raise KiteError(
                f"token exchange failed (HTTP {status}): {_error_message(body)[0]}"
            ) from e
