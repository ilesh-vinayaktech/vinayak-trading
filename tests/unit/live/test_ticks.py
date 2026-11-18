import struct
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from algo.live.ticks import Tick, TickFormatError, parse

RELIANCE = 738561  # segment byte 0x01: prices in paise


def frame(*packets: bytes) -> bytes:
    return struct.pack(">H", len(packets)) + b"".join(
        struct.pack(">H", len(p)) + p for p in packets
    )


def full(token=RELIANCE, ltp=287550, volume=1_234_567, ts=1_794_468_900, last_trade=0):
    # token, ltp, last qty, avg price, volume, buy qty, sell qty, open, high, low, close,
    # last trade time, oi, oi high, oi low, exchange timestamp, then 10 depth entries of 12 bytes
    head = struct.pack(
        ">11i5i",
        token,
        ltp,
        10,
        287000,
        volume,
        500,
        600,
        286000,
        288000,
        285500,
        286500,
        last_trade,
        0,
        0,
        0,
        ts,
    )
    return head + b"\x00" * 120


def quote(token=RELIANCE, ltp=100050, volume=42):
    return struct.pack(">11i", token, ltp, 1, 100000, volume, 5, 6, 99000, 101000, 98000, 99500)


def test_a_full_packet_gives_price_cumulative_volume_and_the_exchange_time():
    (t,) = parse(frame(full()))
    assert t == Tick(
        RELIANCE,
        Decimal("2875.50"),
        1_234_567,
        datetime.fromtimestamp(1_794_468_900, UTC),
        day_open=Decimal("2860.00"),
        day_high=Decimal("2880.00"),
        day_low=Decimal("2855.00"),
        prev_close=Decimal("2865.00"),
    )
    assert isinstance(t.ltp, Decimal)


def test_the_exchanges_own_day_open_high_low_and_previous_close_come_with_quote_and_full_packets():
    (q,) = parse(frame(quote()))
    assert (q.day_open, q.day_high, q.day_low, q.prev_close) == (
        Decimal("990.00"),
        Decimal("1010.00"),
        Decimal("980.00"),
        Decimal("995.00"),
    )
    (p,) = parse(
        frame(struct.pack(">2i", RELIANCE, 100050))
    )  # a price-only packet has none of them
    assert (p.day_open, p.day_high, p.day_low, p.prev_close) == (None, None, None, None)


def test_a_quote_packet_has_no_exchange_time_and_an_ltp_packet_has_no_volume():
    (q,) = parse(frame(quote()))
    assert (q.ltp, q.volume, q.exchange_ts) == (Decimal("1000.50"), 42, None)
    (p,) = parse(frame(struct.pack(">2i", RELIANCE, 100050)))
    assert (p.ltp, p.volume, p.exchange_ts) == (Decimal("1000.50"), None, None)


def test_index_packets_carry_a_price_and_an_optional_time():
    idx = struct.pack(">7i", 256265, 2_450_000, 2_460_000, 2_440_000, 2_445_000, 2_448_000, 2000)
    (a,) = parse(frame(idx))
    assert (a.ltp, a.volume, a.exchange_ts) == (Decimal("24500.00"), None, None)
    (b,) = parse(frame(idx + struct.pack(">i", 1_794_468_900)))
    assert b.exchange_ts == datetime.fromtimestamp(1_794_468_900, UTC)


def test_prices_use_the_divisor_of_the_instruments_segment():
    cds = struct.pack(">2i", (1 << 8) | 3, 830_000_000)  # currency derivatives: 7 decimals
    bcd = struct.pack(">2i", (1 << 8) | 6, 12_345_600)  # BSE currency: 4 decimals
    a, b = parse(frame(cds, bcd))
    assert (a.ltp, b.ltp) == (Decimal("83"), Decimal("1234.56"))


def test_several_packets_in_one_frame_come_out_in_order_and_a_heartbeat_gives_none():
    ticks = parse(
        frame(quote(token=1, ltp=100), full(token=2, ltp=200), struct.pack(">2i", 3, 300))
    )
    assert [t.token for t in ticks] == [1, 2, 3]
    assert parse(b"\x00") == []


@pytest.mark.parametrize(
    "bad",
    [
        b"",
        b"\x00\x01",  # promises a packet, has none
        struct.pack(">H", 1) + struct.pack(">H", 50) + b"\x00" * 50,  # a size Kite does not use
        struct.pack(">H", 1) + struct.pack(">H", 44) + b"\x00" * 10,  # shorter than it says
        frame(quote()) + b"\x00",  # trailing bytes
    ],
)
def test_a_malformed_frame_is_refused_not_guessed_at(bad):
    with pytest.raises(TickFormatError):
        parse(bad)


def test_an_index_packet_carries_the_days_high_low_open_and_previous_close():
    idx = struct.pack(">7i", 256265, 2_450_000, 2_460_000, 2_440_000, 2_445_000, 2_448_000, 2000)
    (a,) = parse(frame(idx))
    assert (a.day_high, a.day_low, a.day_open, a.prev_close) == (
        Decimal("24600.00"),
        Decimal("24400.00"),
        Decimal("24450.00"),
        Decimal("24480.00"),
    )
