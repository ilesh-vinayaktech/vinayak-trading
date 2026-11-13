# ruff: noqa: E501
"""Filed ratios as they were known on a past day, for a strategy. Plain data in, pure functions out: no clock, no database.

The book holds each stock's filings, split/bonus dates and dividends (loaded once by the study runner, like the membership).
`ratios` asks "what would the Screener have shown on this day": only filings made by then (a restatement counts once it is
filed), the same `algo.data.ratios` code the Screener page uses, with the same price basis (the last raw close) and the same
rule that a split or bonus after the latest results blanks the per-share ratios rather than mixing bases."""

from __future__ import annotations

from bisect import bisect_right
from datetime import date, datetime, timedelta
from decimal import Decimal

from algo.data import ratios as fr


class FundamentalsBook:
    def __init__(
        self,
        quarters: dict[tuple[int, str], list[fr.Quarter]],
        splits: dict[int, list[date]],
        dividends: dict[int, list[tuple[date, Decimal]]],
    ) -> None:
        self.quarters, self.splits, self.dividends = (
            quarters,
            splits,
            dividends,
        )  # splits, dividends: oldest first

    def ratios(
        self, iid: int, now: datetime, price: Decimal, price_date: date
    ) -> dict[str, Decimal | None]:
        """Every ratio of this stock known at `now`, priced at `price` (the raw close of `price_date`); {} when nothing is filed yet."""
        day = price_date  # ponytail: no cache (millions of stock-days); each trial recomputes, add one if studies get slow
        known = fr.known_quarters(
            self.quarters.get((iid, "CONSOLIDATED"), []), now
        ) or fr.known_quarters(self.quarters.get((iid, "STANDALONE"), []), now)
        if not known:
            return {}
        splits = self.splits.get(iid, [])
        i = bisect_right(splits, day)
        split_after = i > 0 and splits[i - 1] > known[0].filed_at.date()
        paid = [a for d, a in self.dividends.get(iid, []) if day - timedelta(days=365) < d <= day]
        market = fr.Market(price, day, sum(paid, Decimal(0)) if paid else None, split_after)
        return {k: v.value for k, v in fr.compute(known, market).items()}
