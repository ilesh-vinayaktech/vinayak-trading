"""Performance metrics from a daily equity curve (no risk-free rate; 252 sessions a year)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

TRADING_DAYS = 252


def metrics(equity: Sequence[tuple[date, Decimal]]) -> dict[str, float | None]:
    if len(equity) < 2:
        return {
            "total_return": None,
            "cagr": None,
            "vol": None,
            "sharpe": None,
            "max_drawdown": None,
        }
    vals = [float(v) for _, v in equity]
    if vals[0] <= 0:
        return {
            "total_return": None,
            "cagr": None,
            "vol": None,
            "sharpe": None,
            "max_drawdown": None,
        }
    end = next((i for i, v in enumerate(vals) if v <= 0), len(vals) - 1)  # stop at a wipe-out
    vals, equity = vals[: end + 1], equity[: end + 1]
    rets = [b / a - 1 for a, b in zip(vals, vals[1:], strict=False)]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1) if len(rets) > 1 else 0.0
    sd = math.sqrt(var)
    years = (equity[-1][0] - equity[0][0]).days / 365.25
    peak, mdd = vals[0], 0.0
    for v in vals:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return {
        "total_return": vals[-1] / vals[0] - 1,
        "cagr": (vals[-1] / vals[0]) ** (1 / years) - 1 if years > 0 and vals[0] > 0 else None,
        "vol": sd * math.sqrt(TRADING_DAYS),
        "sharpe": mean / sd * math.sqrt(TRADING_DAYS) if sd > 0 else None,
        "max_drawdown": mdd,
    }
