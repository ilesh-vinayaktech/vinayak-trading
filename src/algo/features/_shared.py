# ruff: noqa: E501
"""Helpers every price feature shares. They are declared as dependencies of each feature's manifest hash: changing this file without a version
bump changes every manifest_sha256 and fails the version guard."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal

DP = Decimal(
    "0.000000000001"
)  # twelve decimals: a stored value is the quantised result, so a hash can be reproduced exactly


@dataclass(frozen=True)
class SessionBar:
    """One session of one instrument. high/low/close are the split- and bonus-adjusted series as of the feature day; raw_* are not adjusted
    (traded value uses them). available_at is when this bar became visible to a reader."""

    day: date
    high: Decimal
    low: Decimal
    close: Decimal
    raw_close: Decimal
    raw_volume: Decimal
    available_at: datetime


Result = dict[
    date, tuple[Decimal, datetime]
]  # day -> (value, available_at); a day with no value is simply absent


def q(x: Decimal) -> Decimal:
    return x.quantize(DP, rounding=ROUND_HALF_EVEN)


def window(
    sessions: Sequence[date], i: int, n: int, bars: Mapping[date, SessionBar]
) -> list[SessionBar] | None:
    """The n bars ending at sessions[i], oldest first; None while there are fewer than n sessions or when ANY of them has no bar (a halted or
    suspended session is a gap, never filled or interpolated)."""
    if i + 1 < n:
        return None
    days = sessions[i - n + 1 : i + 1]
    if any(d not in bars for d in days):
        return None
    return [bars[d] for d in days]


def latest(bars: Sequence[SessionBar]) -> datetime:
    """A value is available only when every input observation is: the latest of their availability times."""
    return max(b.available_at for b in bars)
