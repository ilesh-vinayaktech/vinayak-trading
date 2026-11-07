"""The ONE place that talks HTTP to NSE archives: browser-like headers, min interval between
calls, retry with exponential backoff on 429/5xx/network, typed errors carrying the status."""

from __future__ import annotations

import http.client
import http.cookiejar
import time
import urllib.error
import urllib.request
from collections.abc import Callable

from algo.data.providers.base import NotPublishedError

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Referer": "https://www.nseindia.com/",
    "Accept": "text/csv,*/*",
}


class NseHttpError(Exception):
    def __init__(self, status: int, url: str) -> None:
        super().__init__(f"HTTP {status} for {url}")
        self.status, self.url = status, url


class NotPublished(NseHttpError, NotPublishedError):
    """404: file not (yet) published. On a trading day this is an incident, not a retry."""


class NseClient:
    def __init__(
        self,
        *,
        retries: int = 3,
        backoff: float = 1.0,
        min_interval: float = 1.0,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.retries, self.backoff, self.min_interval = retries, backoff, min_interval
        self.timeout, self._sleep, self._clock = timeout, sleep, clock
        self._last: float | None = None
        self._opener = urllib.request.build_opener(  # session cookies for the JSON APIs
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def _throttle(self) -> None:
        if self._last is not None:
            wait = self.min_interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()

    def warm(self, url: str) -> None:
        """Visit a page to receive session cookies; its own HTTP status is irrelevant."""
        try:
            self.get(url)
        except NseHttpError:
            pass

    def get(self, url: str, accept: str | None = None) -> bytes:
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                headers = {**HEADERS, **({"Accept": accept} if accept else {})}
                req = urllib.request.Request(url, headers=headers)  # noqa: S310
                with self._opener.open(req, timeout=self.timeout) as r:
                    return bytes(r.read())
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    raise NotPublished(404, url) from e
                if e.code != 429 and e.code < 500:
                    raise NseHttpError(e.code, url) from e
                err: Exception = NseHttpError(e.code, url)
            except (
                urllib.error.URLError,
                TimeoutError,
                ConnectionError,
                http.client.HTTPException,
            ) as e:
                err = e
            if attempt == self.retries:
                raise err
            self._sleep(self.backoff * 2**attempt)
        raise AssertionError("unreachable")  # pragma: no cover
