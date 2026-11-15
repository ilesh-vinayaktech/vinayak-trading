# ruff: noqa: E501
"""Fundamental features (family 'fundamental'): the Screener's ratios (algo.data.ratios) as they were KNOWN on each day, point in time.

Callers: algo.features.registry (definitions), the store, job, validation and alpha code through the registry. User's instruction: "do as much as you can do yourself, keep taking things one
by one from @TODO.md and @plan.md". Rules, all about not seeing the future:
  * A filing counts from the session AFTER the day it was filed: a result filed at 16:30 on the 10th is not known during or at the close of the 10th (conservative by up to a day).
  * Consolidated figures are used while the company has any known consolidated quarter, standalone otherwise (the same rule as the Screener); a restatement counts only from the day
    after it was filed.
  * The value holds from one filing to the next. `available_at` is the filing time that produced it, never the value day's own bar.
  * Only ratios that need no price and no per-share figure are features here: valuation ratios depend on the price every day and per-share ratios on splits, so they are left out
    until they get their own treatment. Nothing is imputed: a ratio the engine cannot work out (a loss a year ago, no balance sheet yet) gives no value.
The heavy ratio engine runs once per company (`FilingsHistory.events`), not once per feature or month."""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from algo.data import ratios as fr
from algo.features._shared import Result, SessionBar, q

IST = ZoneInfo(
    "Asia/Kolkata"
)  # sessions are Indian trading days, so a filing's day is its Indian calendar day

# price-free, split-free ratios, in the order they are registered
KEYS: tuple[str, ...] = (
    "revenue_growth",
    "profit_growth",
    "revenue_growth_ttm",
    "profit_growth_ttm",
    "net_margin",
    "operating_margin",
    "roe",
    "roa",
    "roce",
    "debt_to_equity",
    "interest_coverage",
    "net_debt_to_ebitda",
    "current_ratio",
    "asset_turnover",
    "cfo_to_profit",
    "fcf_margin",
)
Filings = Mapping[
    str, Sequence[fr.Quarter]
]  # basis ("CONSOLIDATED" / "STANDALONE") -> every filing of one company


class FilingsHistory:
    """One company's filings, with the ratios known after each filing worked out once and kept."""

    def __init__(self, filings: Filings) -> None:
        self.filings = {basis: list(qs) for basis, qs in filings.items()}
        self._events: list[tuple[datetime, dict[str, Decimal | None]]] | None = None
        self._dates: list[date] | None = None
        self._cuts: dict[date, FilingsHistory] = {}

    @property
    def events(self) -> list[tuple[datetime, dict[str, Decimal | None]]]:
        """[(filing time, {ratio: value or None})] oldest first: the ratios as known right after each filing."""
        if self._events is None:
            consolidated, standalone = (
                self.filings.get("CONSOLIDATED", []),
                self.filings.get("STANDALONE", []),
            )
            times = sorted({f.filed_at for qs in self.filings.values() for f in qs})
            self._events = []
            for t in times:
                known = fr.known_quarters(consolidated, t) or fr.known_quarters(standalone, t)
                ratios = fr.compute(known, None)
                self._events.append(
                    (t, {k: (ratios[k].value if k in ratios else None) for k in KEYS})
                )
            self._dates = [t.astimezone(IST).date() for t, _ in self._events]
        return self._events

    def truncated(self, cut: date) -> FilingsHistory:
        """The same company as it was known at the end of `cut`: only filings made on or before that Indian day (the look-ahead check recomputes from this). Kept per cut, so
        every feature checked against the same cut shares one worked-out history."""
        if cut not in self._cuts:
            self._cuts[cut] = FilingsHistory(
                {
                    b: [f for f in qs if f.filed_at.astimezone(IST).date() <= cut]
                    for b, qs in self.filings.items()
                }
            )
        return self._cuts[cut]

    @property
    def event_dates(self) -> list[date]:
        _ = self.events
        assert self._dates is not None
        return self._dates


def ratio(
    key: str,
) -> Callable[[Sequence[date], Mapping[date, SessionBar], FilingsHistory], Result]:
    """The ratio `key` as known on each session on which the company has a bar: from the session after the latest filing that gives it a value."""
    if key not in KEYS:
        raise ValueError(f"{key} is not a fundamental feature")

    def f(
        sessions: Sequence[date], bars: Mapping[date, SessionBar], history: FilingsHistory
    ) -> Result:
        out: Result = {}
        events, dates = history.events, history.event_dates
        if not events:
            return out
        for d in sessions:
            if d not in bars:
                continue
            k = bisect_left(dates, d) - 1  # the last filing made on a day BEFORE d
            if k < 0:
                continue
            when, values = events[k]
            v = values.get(key)
            if v is not None:
                out[d] = (q(v), when)
        return out

    return f
