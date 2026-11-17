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
MARKET_MAX_AGE_DAYS = 5  # the zone is stored for every trading day: a reading older than a long weekend is missing data, not a reading
MARKET_FIELDS = (
    "mkt_fear_greed",
    "mkt_bull",
    "mkt_stressed",
)  # the market zone as known on the day: the same for every stock (a regime filter)
FIELDS = (
    "score",
    "score_trend",
    "score_participation",
    "score_smart_money",
    "score_quality",
)  # the numeric score fields a screen may use (setup and score_why are text)


class ScoreBook:
    def __init__(
        self,
        rows: dict[int, list[tuple[date, dict[str, float]]]],
        market: list[tuple[date, dict[str, float]]] | None = None,
    ) -> None:
        """`rows`: instrument id -> [(day, {field: value})], oldest first. `market`: [(day, {mkt_ field: value})], oldest first."""
        self.rows = rows
        self._days = {iid: [d for d, _ in r] for iid, r in rows.items()}
        self.market = market or []
        self._market_days = [d for d, _ in self.market]

    def market_on(self, day: date) -> dict[str, Decimal]:
        """The market zone fields as known on `day`; {} when there is no row recent enough."""
        i = bisect_right(self._market_days, day) - 1
        if i < 0 or (day - self._market_days[i]).days > MARKET_MAX_AGE_DAYS:
            return {}
        return {k: Decimal(str(v)) for k, v in self.market[i][1].items() if k in MARKET_FIELDS}

    def fields(self, iid: int, day: date) -> dict[str, Decimal]:
        """The score fields of this stock as known on `day` plus the market zone fields of that day; a part with no recent enough row is simply absent."""
        out = self.market_on(day)
        days = self._days.get(iid)
        if days:
            i = bisect_right(days, day) - 1
            if i >= 0 and (day - days[i]).days <= MAX_AGE_DAYS:
                out.update(
                    {k: Decimal(str(v)) for k, v in self.rows[iid][i][1].items() if k in FIELDS}
                )
        return out

    def digest(self) -> str:
        """A fingerprint of every row held, so a run can record exactly which scores it read (a rebuilt history gives a different one)."""
        h = hashlib.sha256()
        for iid in sorted(self.rows):
            for day, vals in self.rows[iid]:
                h.update(f"{iid}|{day.isoformat()}|{sorted(vals.items())}\n".encode())
        for day, vals in self.market:
            h.update(f"market|{day.isoformat()}|{sorted(vals.items())}\n".encode())
        return h.hexdigest()
