# ruff: noqa: E501
"""The swing score as it was known on a day, for a screener strategy (TODO 6.13). Like `FundamentalsBook` it is plain data loaded before the run (a strategy holds no
database): rows of (day, score fields) per stock from `stock_score_history`, each built only from what was known on its own day. On a decision day the newest row dated on or
before it is used, and only if it is at most MAX_AGE_DAYS old (the backfill is weekly, tonight's job daily); an older row, or none, gives NO figure, and a screen never matches on
a missing figure. A row dated after the day is invisible (tested)."""

from __future__ import annotations

import hashlib
from bisect import bisect_right
from datetime import date
from decimal import Decimal

MAX_AGE_DAYS = 10
FIELDS = (
    "score",
    "score_trend",
    "score_participation",
    "score_smart_money",
    "score_quality",
)  # the numeric score fields a screen may use (setup and score_why are text)


class ScoreBook:
    def __init__(self, rows: dict[int, list[tuple[date, dict[str, float]]]]) -> None:
        """`rows`: instrument id -> [(day, {field: value})], oldest first."""
        self.rows = rows
        self._days = {iid: [d for d, _ in r] for iid, r in rows.items()}

    def fields(self, iid: int, day: date) -> dict[str, Decimal]:
        """The score fields of this stock as known on `day`; {} when there is none recent enough."""
        days = self._days.get(iid)
        if not days:
            return {}
        i = bisect_right(days, day) - 1
        if i < 0 or (day - days[i]).days > MAX_AGE_DAYS:
            return {}
        return {k: Decimal(str(v)) for k, v in self.rows[iid][i][1].items() if k in FIELDS}

    def digest(self) -> str:
        """A fingerprint of every row held, so a run can record exactly which scores it read (a rebuilt history gives a different one)."""
        h = hashlib.sha256()
        for iid in sorted(self.rows):
            for day, vals in self.rows[iid]:
                h.update(f"{iid}|{day.isoformat()}|{sorted(vals.items())}\n".encode())
        return h.hexdigest()
