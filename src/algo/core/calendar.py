"""Exchange calendars. Holidays are data (loaded from the exchange list), never hard-coded.
Bar timestamps are bar-OPEN, UTC. A bar is visible only after it closes."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from algo.core.clock import require_utc


@dataclass(frozen=True)
class SessionInfo:
    """What is known about one day's session, kept apart so nothing provisional reads as verified.
    existence: EVIDENCED (listed from data) | RULE (weekday, not a holiday) | NONE (closed).
    kind_status: CONFIRMED | UNCONFIRMED | NOT_APPLICABLE.
    hours_status: VERIFIED | RULE (the regular session) | UNKNOWN (not documented).
    bar_visibility: RULE | ASSUMPTION (regular hours applied only so bars can be made visible)."""

    day: date
    session_type: str
    existence: str
    kind_status: str
    hours: tuple[time, time] | None
    hours_status: str
    bar_visibility: str


class SessionCalendar:
    """Fixed daily session in one timezone, Mon-Fri minus holidays (NSE-style)."""

    def __init__(
        self,
        tz: str,
        open_t: time,
        close_t: time,
        holidays: Iterable[date] = (),
        special: dict[date, tuple[time, time]] | None = None,
        special_kinds: dict[date, str] | None = None,
        special_status: Mapping[date, tuple[str, str]] | None = None,
    ) -> None:
        self.tz = ZoneInfo(tz)
        self.open_t, self.close_t = open_t, close_t
        self.holidays = frozenset(holidays)
        self.special = special or {}  # Muhurat etc: date -> (open, close)
        self.special_kinds = special_kinds or {}  # date -> "SPECIAL" | "MUHURAT" (default SPECIAL)
        # date -> (kind_status, hours_status); absent means unconfirmed kind and unknown hours
        self.special_status = special_status or {}

    def _hours(self, d: date) -> tuple[time, time] | None:
        if d in self.special:
            return self.special[d]
        if d.weekday() >= 5 or d in self.holidays:
            return None
        return self.open_t, self.close_t

    def session_type(self, d: date) -> str:
        """REGULAR (weekday), SPECIAL / MUHURAT (an evidenced extra session, weekday or weekend),
        or CLOSED. Driven by the holiday and special-session DATA, never by the weekday alone."""
        if d in self.special:
            return self.special_kinds.get(d, "SPECIAL")
        return "CLOSED" if self._hours(d) is None else "REGULAR"

    def session_info(self, d: date) -> SessionInfo:
        kind = self.session_type(d)
        if d in self.special:
            ks, hs = self.special_status.get(d, ("UNCONFIRMED", "UNKNOWN"))
            verified = hs == "VERIFIED"
            return SessionInfo(d, kind, "EVIDENCED", ks, self.special[d] if verified else None,
                               hs, "RULE" if verified else "ASSUMPTION")  # fmt: skip
        if kind == "CLOSED":
            return SessionInfo(d, kind, "NONE", "NOT_APPLICABLE", None, "NOT_APPLICABLE", "RULE")
        return SessionInfo(d, kind, "RULE", "NOT_APPLICABLE", (self.open_t, self.close_t), "RULE",
                           "RULE")  # fmt: skip

    def is_trading_day(self, d: date) -> bool:
        return self._hours(d) is not None

    def session(self, d: date) -> tuple[datetime, datetime] | None:
        h = self._hours(d)
        if h is None:
            return None
        o = datetime.combine(d, h[0], self.tz).astimezone(UTC)
        c = datetime.combine(d, h[1], self.tz).astimezone(UTC)
        return o, c

    def session_bars(self, d: date, minutes: int = 1) -> list[datetime]:
        """Bar-open timestamps (UTC) for the day."""
        s = self.session(d)
        if s is None:
            return []
        out, t = [], s[0]
        while t + timedelta(minutes=minutes) <= s[1]:
            out.append(t)
            t += timedelta(minutes=minutes)
        return out

    def is_open(self, ts: datetime) -> bool:
        ts = require_utc(ts)
        s = self.session(ts.astimezone(self.tz).date())
        return s is not None and s[0] <= ts < s[1]

    def next_bar_boundary(self, ts: datetime, minutes: int = 1) -> datetime:
        """First bar-open strictly after ts (rolls to the next trading day)."""
        ts = require_utc(ts)
        d = ts.astimezone(self.tz).date()
        for _ in range(400):
            for b in self.session_bars(d, minutes):
                if b > ts:
                    return b
            d += timedelta(days=1)
        raise RuntimeError("no trading day within 400 days; holiday data missing?")

    def prev_session(self, d: date) -> date:
        d -= timedelta(days=1)
        while not self.is_trading_day(d):
            d -= timedelta(days=1)
        return d


def nse(
    holidays: Iterable[date] = (),
    special: dict[date, tuple[time, time]] | None = None,
    special_kinds: dict[date, str] | None = None,
    special_status: Mapping[date, tuple[str, str]] | None = None,
) -> SessionCalendar:
    return SessionCalendar(
        "Asia/Kolkata", time(9, 15), time(15, 30), holidays, special, special_kinds, special_status
    )
