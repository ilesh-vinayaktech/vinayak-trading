from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from algo.live.bars import BarBuilder, LiveBar
from algo.live.ticks import Tick

# 2026-11-12 is a Thursday; 09:15 IST = 03:45 UTC
OPEN = datetime(2026, 11, 12, 3, 45, tzinfo=UTC)


def at(minute: int, second: int = 0) -> datetime:
    return OPEN + timedelta(minutes=minute, seconds=second)


def tick(price, volume, when, token=1):
    return Tick(token, D(str(price)), volume, when)


def test_ticks_in_a_minute_make_one_bar_with_ohlc_and_the_volume_traded_in_that_minute():
    b = BarBuilder()
    assert b.on_tick(tick(100, 1000, at(0, 1)), at(0, 1)) == []
    assert b.on_tick(tick(102, 1300, at(0, 20)), at(0, 20)) == []
    assert b.on_tick(tick(99, 1500, at(0, 50)), at(0, 50)) == []
    (bar,) = b.on_tick(tick(101, 1600, at(1, 2)), at(1, 2))  # the next minute closes the first
    assert bar == LiveBar(1, at(0), D(100), D(102), D(99), D(99), 500, 3, partial=False)


def test_volume_continues_across_minutes_from_the_running_total():
    b = BarBuilder()
    b.on_tick(tick(100, 1000, at(0)), at(0))
    (first,) = b.on_tick(tick(101, 1400, at(1)), at(1))
    b.on_tick(tick(102, 1900, at(1, 30)), at(1, 30))
    (second,) = b.on_tick(tick(103, 2000, at(2)), at(2))
    assert (first.volume, second.volume) == (0, 900)  # minute 1 got 400 (1000->1400) then 500 more


def test_joining_mid_session_marks_the_first_bar_partial_because_earlier_volume_is_unknown():
    b = BarBuilder()
    b.on_tick(tick(100, 50_000, at(30)), at(30))
    b.on_tick(tick(101, 50_400, at(30, 40)), at(30, 40))
    (bar,) = b.on_tick(tick(101, 50_500, at(31)), at(31))
    assert bar.partial and bar.volume == 400
    (nxt,) = b.flush(at(33))
    assert not nxt.partial


def test_a_session_open_start_is_not_partial_and_a_packet_without_volume_is():
    b = BarBuilder()
    b.on_tick(tick(100, 10, at(0, 1)), at(0, 1))
    (bar,) = b.flush(at(2))
    assert not bar.partial and bar.volume == 0
    b.on_tick(Tick(2, D(5), None, at(5)), at(5))
    (ltp_only,) = b.flush(at(7))
    assert ltp_only.partial and ltp_only.volume == 0


def test_a_volume_that_goes_backwards_is_not_counted_and_flags_the_bar():
    b = BarBuilder()
    b.on_tick(tick(100, 1000, at(0)), at(0))
    b.on_tick(tick(100, 900, at(0, 30)), at(0, 30))
    (bar,) = b.flush(at(2))
    assert bar.volume == 0 and bar.partial and b.stats["volume_reset"] == 1


def test_flush_closes_only_minutes_that_have_ended_and_waits_for_late_ticks():
    b = BarBuilder(grace=timedelta(seconds=2))
    b.on_tick(tick(100, 10, at(0, 5)), at(0, 5))
    assert b.flush(at(1, 1)) == []  # inside the grace period
    assert [x.ts for x in b.flush(at(1, 3))] == [at(0)]
    assert b.flush(at(5)) == []  # nothing left open


def test_a_late_tick_for_a_minute_already_closed_is_dropped_and_counted():
    b = BarBuilder()
    b.on_tick(tick(100, 10, at(0)), at(0))
    b.on_tick(tick(101, 20, at(1)), at(1))
    assert b.on_tick(tick(500, 30, at(0, 40)), at(1, 5)) == []
    (bar,) = b.flush(at(3))
    assert bar.ts == at(1) and bar.close == D(101) and b.stats["late"] == 1


def test_only_session_minutes_count_and_the_received_time_is_used_when_the_exchange_sends_none():
    b = BarBuilder()
    before_open = OPEN - timedelta(minutes=1)
    after_close = OPEN + timedelta(minutes=375)  # 15:30 IST
    for when in (before_open, after_close):
        assert b.on_tick(tick(100, 1, when), when) == []
    assert b.stats["outside_session"] == 2 and b.flush(after_close + timedelta(hours=1)) == []
    b.on_tick(Tick(1, D(7), 5, None), at(10, 3))
    (bar,) = b.flush(at(12))
    assert bar.ts == at(10)


def test_each_instrument_has_its_own_bar():
    b = BarBuilder()
    b.on_tick(tick(100, 10, at(0), token=1), at(0))
    b.on_tick(tick(200, 20, at(0), token=2), at(0))
    assert sorted((x.token, x.close) for x in b.flush(at(2))) == [(1, D(100)), (2, D(200))]


def test_after_a_gap_the_next_tick_is_a_new_baseline_so_the_outage_volume_is_not_dumped_in_one_minute():
    b = BarBuilder()
    b.on_tick(tick(100, 1000, at(30)), at(30))
    b.reset_baselines()  # the connection dropped and came back
    b.on_tick(tick(101, 9000, at(34)), at(34))  # 8000 traded while we were away
    (old,) = b.on_tick(tick(101, 9100, at(35)), at(35))
    assert old.ts == at(34) and old.volume == 0 and old.partial
    (new,) = b.flush(at(37))
    assert new.volume == 100 and not new.partial
