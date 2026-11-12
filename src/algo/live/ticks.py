# ruff: noqa: E501
"""Kite's binary WebSocket frames -> ticks.

A frame is: packet count (2 bytes), then per packet a length (2 bytes) and that many bytes, all big-endian. Packet sizes
Kite uses: 8 (last price only), 28 / 32 (index, 32 adds a time), 44 (quote) and 184 (full: adds the last-trade and
exchange times, open interest and market depth). Prices arrive as integers in the smallest unit of the instrument's
segment (paise for equities) and become exact Decimals here. A one-byte frame is a heartbeat. A frame that does not
parse exactly is refused whole: guessing at a half-understood frame would put wrong prices into bars."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

SIZES = {8, 28, 32, 44, 184}
DIVISORS = {
    3: Decimal(10_000_000),
    6: Decimal(10_000),
}  # currency segments; everything else is hundredths
DEFAULT_DIVISOR = Decimal(100)


class TickFormatError(Exception):
    pass


@dataclass(frozen=True)
class Tick:
    token: int
    ltp: Decimal
    volume: int | None  # traded so far today (cumulative); None where the packet has none
    exchange_ts: datetime | None  # UTC; None where the packet has none
    # the exchange's own figures for the day so far (quote and full packets only): they stay right even if we joined mid-session
    day_open: Decimal | None = None
    day_high: Decimal | None = None
    day_low: Decimal | None = None
    prev_close: Decimal | None = None


def _time(epoch: int) -> datetime | None:
    return datetime.fromtimestamp(epoch, UTC) if epoch else None


def _packet(p: bytes) -> Tick:
    token, raw = struct.unpack_from(">2i", p)
    ltp = Decimal(raw) / DIVISORS.get(token & 0xFF, DEFAULT_DIVISOR)
    if len(p) == 8:
        return Tick(token, ltp, None, None)
    if len(p) in (28, 32):  # index: no volume; the 32-byte form ends with the exchange time
        return Tick(
            token, ltp, None, _time(struct.unpack_from(">i", p, 28)[0]) if len(p) == 32 else None
        )
    volume = struct.unpack_from(">i", p, 16)[0]
    div = DIVISORS.get(token & 0xFF, DEFAULT_DIVISOR)
    day = [
        Decimal(x) / div for x in struct.unpack_from(">4i", p, 28)
    ]  # open, high, low, previous close
    if len(p) == 44:
        return Tick(token, ltp, volume, None, *day)
    last_trade, exchange = struct.unpack_from(">i", p, 44)[0], struct.unpack_from(">i", p, 60)[0]
    return Tick(token, ltp, volume, _time(exchange or last_trade), *day)


def parse(data: bytes) -> list[Tick]:
    if len(data) == 1:
        return []  # heartbeat
    if len(data) < 2:
        raise TickFormatError("frame too short")
    (count,) = struct.unpack_from(">H", data)
    at, out = 2, []
    for _ in range(count):
        if at + 2 > len(data):
            raise TickFormatError("frame ends before a packet length")
        (n,) = struct.unpack_from(">H", data, at)
        at += 2
        if n not in SIZES:
            raise TickFormatError(f"unexpected packet size {n}")
        if at + n > len(data):
            raise TickFormatError("packet is shorter than its length says")
        out.append(_packet(data[at : at + n]))
        at += n
    if at != len(data):
        raise TickFormatError("bytes left over after the last packet")
    return out
