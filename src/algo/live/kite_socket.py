# ruff: noqa: E501
"""The one place that talks WebSocket to Kite. Everything above it sees `send(text)` and `recv() -> text | bytes`.

A login the server refuses (401/403: the daily token is gone) becomes KiteTokenExpired, which must never be retried;
every other failure (refused, unreachable, dropped mid-stream) becomes a plain OSError the caller reconnects after.
The access token travels in the URL Kite requires; this module never logs or puts it into an error message."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlencode

from websockets.asyncio.client import ClientConnection
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed, InvalidStatus, WebSocketException

from algo.data.providers.kite import KiteTokenExpired

URL = "wss://ws.kite.trade"


class KiteSocket:
    def __init__(self, ws: ClientConnection) -> None:
        self._ws = ws

    async def send(self, message: str) -> None:
        try:
            await self._ws.send(message)
        except ConnectionClosed as e:
            raise ConnectionError("connection closed") from e

    async def recv(self) -> str | bytes:
        try:
            return await self._ws.recv()
        except ConnectionClosed as e:
            raise ConnectionError("connection closed") from e


@asynccontextmanager
async def connect(api_key: str, access_token: str, *, url: str = URL) -> AsyncIterator[KiteSocket]:
    query = urlencode({"api_key": api_key, "access_token": access_token})
    try:
        async with ws_connect(f"{url}?{query}", open_timeout=15, max_size=None) as ws:
            yield KiteSocket(ws)
    except InvalidStatus as e:
        status = e.response.status_code
        if status in (401, 403):
            raise KiteTokenExpired(f"Kite refused the WebSocket login ({status})") from None
        raise ConnectionError(f"Kite refused the WebSocket connection ({status})") from None
    except WebSocketException as e:
        raise ConnectionError(type(e).__name__) from None
