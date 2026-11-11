# ruff: noqa: E501
"""Ticks -> 1-minute bars, the way an exchange session defines them.

A bar covers one session minute (09:15 to 15:29 IST); `ts` is its open, in UTC. It is emitted once, when the next minute
starts for that instrument or `flush` finds its minute ended (plus a short grace for slow ticks). Volume is what traded
in the minute: the difference of the running day total between ticks. Joining mid-session, or a total that goes backwards,
leaves the minute's volume understated, so that bar is flagged `partial` rather than passed off as exact. A tick for a minute
already emitted is dropped and counted: bars are never revised after they leave. No tick in a minute means no bar."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from algo.live.ticks import Tick

IST = ZoneInfo("Asia/Kolkata")
SESSION_OPEN, SESSION_CLOSE = time(9, 15), time(15, 30)
MINUTE = timedelta(minutes=1)


@dataclass(frozen=True)
class LiveBar:
    token: int
    ts: datetime  # minute open, UTC
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    ticks: int
    partial: bool


@dataclass
class _Open:
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    ticks: int
    partial: bool

    def bar(self, token: int) -> LiveBar:
        return LiveBar(
            token,
            self.ts,
            self.open,
            self.high,
            self.low,
            self.close,
            self.volume,
            self.ticks,
            self.partial,
        )


class BarBuilder:
    def __init__(
        self,
        grace: timedelta = timedelta(seconds=2),
        windows: Sequence[tuple[datetime, datetime]] | None = None,
    ) -> None:
        """`windows`: the day's trading windows as UTC (start, end); None means the regular 09:15-15:30 IST session."""
        self.grace = grace
        self.windows = windows
        self.stats: Counter[str] = Counter()
        self._open: dict[int, _Open] = {}
        self._total: dict[int, int] = {}  # last running day volume seen per instrument

    def on_tick(self, t: Tick, received_at: datetime) -> list[LiveBar]:
        when = (t.exchange_ts or received_at).astimezone(UTC)
        minute = when.replace(second=0, microsecond=0)
        opens = self._session_opens(when, minute)
        if opens is None:
            self.stats["outside_session"] += 1
            return []
        current = self._open.get(t.token)
        if current is not None and minute < current.ts:
            self.stats["late"] += 1
            return []
        delta, partial = self._volume(t, opens)
        out: list[LiveBar] = []
        if current is not None and minute > current.ts:
            out.append(current.bar(t.token))
            current = None
        if current is None:
            current = self._open[t.token] = _Open(minute, t.ltp, t.ltp, t.ltp, t.ltp, 0, 0, False)
        current.high, current.low, current.close = (
            max(current.high, t.ltp),
            min(current.low, t.ltp),
            t.ltp,
        )
        current.volume += delta
        current.ticks += 1
        current.partial = current.partial or partial
        return out

    def _session_opens(self, when: datetime, minute: datetime) -> bool | None:
        """None when `when` is outside every trading window; else whether `minute` is the first minute of its window."""
        if self.windows is None:
            local = when.astimezone(IST).time()
            return (
                minute.astimezone(IST).time() == SESSION_OPEN
                if SESSION_OPEN <= local < SESSION_CLOSE
                else None
            )
        for start, end in self.windows:
            if start <= when < end:
                return minute == start.replace(second=0, microsecond=0)
        return None

    def _volume(self, t: Tick, at_open: bool) -> tuple[int, bool]:
        """(volume since the previous tick of this instrument, whether that figure is unreliable)."""
        previous = self._total.get(t.token)
        if t.volume is None:
            return 0, True
        self._total[t.token] = t.volume
        if previous is None:
            return 0, not at_open  # no earlier total: exact only if the session has just begun
        if t.volume < previous:
            self.stats["volume_reset"] += 1
            return 0, True
        return t.volume - previous, False

    def reset_baselines(self) -> None:
        """Call after the connection was lost: the next tick of each instrument starts a new running total (its minute is flagged partial)."""
        self._total.clear()

    def flush(self, now: datetime) -> list[LiveBar]:
        done = [tok for tok, o in self._open.items() if now >= o.ts + MINUTE + self.grace]
        return [self._open.pop(tok).bar(tok) for tok in done]
