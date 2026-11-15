# ruff: noqa: E501
"""Live (paper) versus model: how far a paper account's equity strays from a backtest of the same strategy over the same days.

Both curves are rebased to the first day they have in common, so a different starting capital does not count as a gap. Pure functions on two
{day: equity} mappings; `scripts/paper_tracking.py` reads them from the database."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

TRADING_DAYS = 252


@dataclass(frozen=True)
class Tracking:
    days: int  # daily returns compared
    first: date | None
    last: date | None
    live_return: Decimal | None
    model_return: Decimal | None
    final_gap: float | None  # live return minus model return over the whole overlap
    max_daily_gap: float | None  # largest absolute difference of one day's returns
    tracking_error: (
        float | None
    )  # annualised standard deviation of the daily return differences; None below two returns


def compare(live: Mapping[date, Decimal], model: Mapping[date, Decimal]) -> Tracking:
    common = sorted(set(live) & set(model))
    if len(common) < 2:
        return Tracking(0, None, None, None, None, None, None, None)
    lv, mv = [float(live[d]) for d in common], [float(model[d]) for d in common]
    diffs = [(lv[i] / lv[i - 1] - 1) - (mv[i] / mv[i - 1] - 1) for i in range(1, len(common))]
    te = None
    if len(diffs) > 1:
        mean = sum(diffs) / len(diffs)
        te = math.sqrt(sum((x - mean) ** 2 for x in diffs) / (len(diffs) - 1)) * math.sqrt(
            TRADING_DAYS
        )
    live_ret, model_ret = (
        live[common[-1]] / live[common[0]] - 1,
        model[common[-1]] / model[common[0]] - 1,
    )
    return Tracking(
        len(diffs), common[0], common[-1], live_ret, model_ret,
        float(live_ret - model_ret), max(abs(x) for x in diffs), te,
    )  # fmt: skip


def breached(t: Tracking, *, max_tracking_error: float) -> bool:
    """True when the annualised tracking error is over the allowance; with too little overlap to judge, False."""
    return t.tracking_error is not None and t.tracking_error > max_tracking_error
