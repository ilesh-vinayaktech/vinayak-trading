# ruff: noqa: E501
"""The live market-data service: Kite WebSocket -> ticks -> 1-minute bars -> database.

One loop per connection: subscribe, then read frames; every frame updates the bar builder, and every second the bars
whose minute ended are stored. The loop is deliberately single-threaded and clock-driven (an injected Clock and sleep),
so it is tested end to end with a scripted socket and a real database.
A dropped or silent connection (no frame, not even a heartbeat, for `dead_after` seconds) is reopened with growing waits
(1, 2, 4 ... 60 s); volume totals restart after a reconnect, so the minute that spans the gap is flagged partial. A login
Kite refuses means the daily token is gone: the service says so and stops instead of retrying. Database writes are
synchronous (a few milliseconds a second); ponytail: move them to a thread only if the stream ever falls behind."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timedelta
from typing import Protocol

import psycopg

from algo.core.clock import Clock
from algo.data.providers.kite import KiteTokenExpired
from algo.live.bar_store import save_bars, save_quotes, save_status
from algo.live.bars import BarBuilder, LiveBar
from algo.live.ticks import Tick, TickFormatError, parse

BACKOFF_CAP = 60


class Socket(Protocol):
    async def send(self, message: str) -> None: ...
    async def recv(self) -> str | bytes: ...


class Feed:
    def __init__(
        self,
        connect: Callable[[], AbstractAsyncContextManager[Socket]],
        conn: psycopg.Connection,
        ids: Mapping[int, int],
        clock: Clock,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        builder: BarBuilder | None = None,
        batch: int = 500,
        mode: str = "full",
        recv_timeout: float = 1.0,
        dead_after: float = 30.0,
        flush_every: float = 1.0,
        status_every: float = 5.0,
        quote_every: float = 2.0,
        until: datetime | None = None,
        frame_sink: Callable[[bytes, datetime], None] | None = None,
    ) -> None:
        self._connect, self._conn, self.ids, self.clock, self._sleep = (
            connect,
            conn,
            ids,
            clock,
            sleep,
        )
        self.builder = builder or BarBuilder()
        self.batch, self.mode, self.recv_timeout, self.dead_after = (
            batch,
            mode,
            recv_timeout,
            dead_after,
        )
        self.quote_every = quote_every
        self._quotes: dict[
            int, Tick
        ] = {}  # the latest tick of each followed stock since the last publish
        self.flush_every, self.status_every, self.until, self.frame_sink = (
            flush_every,
            status_every,
            until,
            frame_sink,
        )
        self.ticks = self.bars = self.bad_frames = self.unknown = 0
        self.last_tick_at: datetime | None = None
        self.last_bar_at: datetime | None = None
        self.notice = ""
        self._state, self._detail = "STARTING", ""
        self._stopping, self._reason = False, "stopped"
        self._got_frame = False
        now = clock.now()
        self._last_flush = self._last_status = self._last_quote = now

    def stop(self, reason: str = "stopped") -> None:
        self._stopping, self._reason = True, reason

    async def run(self) -> str:
        """Run until stopped; returns the final state: STOPPED, or TOKEN_EXPIRED when Kite refused the login."""
        self._save("STARTING", "")
        failures, first = 0, True
        while not self._stopping:
            self._got_frame = False
            try:
                async with self._connect() as sock:
                    if not first:
                        self.builder.reset_baselines()
                    first = False
                    await self._subscribe(sock)
                    self._save("CONNECTED", f"{len(self.ids)} instruments")
                    await self._read(sock)
            except KiteTokenExpired:
                self._save(
                    "TOKEN_EXPIRED",
                    "Kite refused the login. Connect to Zerodha again, then start the feed.",
                )
                return "TOKEN_EXPIRED"
            except OSError as e:
                if self._stopping:
                    break
                if self._got_frame:
                    failures = 0
                delay = min(2**failures, BACKOFF_CAP)
                failures += 1
                self._save("RECONNECTING", f"{type(e).__name__}: {e}; retrying in {delay} s")
                await self._sleep(delay)
        self._publish_quotes(self.clock.now())
        self._save("STOPPED", self._reason)
        return "STOPPED"

    async def _subscribe(self, sock: Socket) -> None:
        tokens = list(self.ids)
        for i in range(0, len(tokens), self.batch):
            chunk = tokens[i : i + self.batch]
            await sock.send(json.dumps({"a": "subscribe", "v": chunk}))
            await sock.send(json.dumps({"a": "mode", "v": [self.mode, chunk]}))

    async def _read(self, sock: Socket) -> None:
        last_frame = self.clock.now()
        while not self._stopping:
            try:
                message = await asyncio.wait_for(sock.recv(), self.recv_timeout)
            except TimeoutError:
                now = self.clock.now()
                if (now - last_frame).total_seconds() > self.dead_after:
                    raise ConnectionError("no data from Kite") from None
                self._housekeeping(now)
                continue
            now = last_frame = self.clock.now()
            self._got_frame = True
            if isinstance(message, bytes):
                self._binary(message, now)
            else:
                self._text(message)
            self._housekeeping(now)

    def _binary(self, data: bytes, now: datetime) -> None:
        if self.frame_sink is not None:
            self.frame_sink(data, now)
        try:
            found = parse(data)
        except TickFormatError:
            self.bad_frames += 1
            return
        for t in found:
            if t.token not in self.ids:
                self.unknown += 1
                continue
            self.ticks += 1
            self.last_tick_at = now
            self._quotes[t.token] = t
            self._emit(self.builder.on_tick(t, now))

    def _text(self, message: str) -> None:
        try:
            doc = json.loads(message)
        except ValueError:
            return
        if isinstance(doc, dict) and doc.get("type") == "error":
            self.notice = str(doc.get("data"))

    def _emit(self, bars: list[LiveBar]) -> None:
        if not bars:
            return
        now = self.clock.now()
        n = save_bars(self._conn, bars, self.ids, now)
        self.bars += n
        self.last_bar_at = now

    def _housekeeping(self, now: datetime) -> None:
        if self.until is not None and now >= self.until:
            self._emit(self.builder.flush(now))
            self.stop("reached the end time")
            return
        if now - self._last_flush >= timedelta(seconds=self.flush_every):
            self._emit(self.builder.flush(now))
            self._last_flush = now
        if now - self._last_quote >= timedelta(seconds=self.quote_every):
            self._publish_quotes(now)
        if now - self._last_status >= timedelta(seconds=self.status_every):
            self._save(self._state, self._detail)

    def _publish_quotes(self, now: datetime) -> None:
        """Write the latest tick of each stock seen since the last publish, for the charts."""
        self._last_quote = now
        if self._quotes:
            save_quotes(self._conn, self._quotes, self.ids, now)
            self._quotes = {}

    def _save(self, state: str, detail: str) -> None:
        self._state, self._detail = state, detail
        now = self.clock.now()
        self._last_status = now
        shown = f"{detail} Last notice from Kite: {self.notice}".strip() if self.notice else detail
        save_status(
            self._conn,
            state,
            shown,
            subscribed=len(self.ids),
            last_tick_at=self.last_tick_at,
            last_bar_at=self.last_bar_at,
            ticks=self.ticks,
            bars=self.bars,
            bad_frames=self.bad_frames,
            late_ticks=self.builder.stats["late"],
            now=now,
        )
