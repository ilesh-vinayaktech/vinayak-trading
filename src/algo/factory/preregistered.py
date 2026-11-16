# ruff: noqa: E501
"""Three return-oriented strategies written down BEFORE any result (review 2026-11-16, section 3.7: the strategies found so far are defensive, the factor most linked to return was thrown out).

Callers: scripts/register_preregistered.py and tests/unit/factory/test_preregistered.py. Nothing similar exists: algo.factory.generate writes definitions from alpha candidates, these are chosen from published
research in advance. User's instruction: "fix all the suggestion as per @docs/research-review-2026-11-16.md".

  * MOMENTUM_12M_M: hold the strongest fifth of stocks by 12-month return, monthly, 15 equal positions, sell when a stock falls into the weak half.
  * MOMENTUM_LOWVOL_M: the same, but only among the calmer two thirds by 60-day volatility (momentum is strongest and least crash-prone among calmer stocks).
  * MOMENTUM_TREND_M: the same as the first, with a market filter: no new buys while under 50% of the stocks are above their 200-day average, and everything is sold when under 40%.
The shares are round priors fixed here, not tuned; nothing in them is fitted to any result."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg

from algo.factory import registry
from algo.factory.dsl import MARKET_BREADTH, StrategyDef

ENTRY_SHARE = 20
EXIT_SHARE = 50
CALM_SHARE = 67  # the calmer two thirds by volatility
POSITIONS = 15
MARKET_IN = 50
MARKET_OUT = 40
_WHY = "Pre-registered from published research before any result (review 2026-11-16). "


def _def(
    strategy_id: str, description: str, entry: list[dict[str, Any]], exit_: list[dict[str, Any]]
) -> StrategyDef:
    return StrategyDef.model_validate(
        {
            "strategy_id": strategy_id, "version": 1, "description": _WHY + description, "universe": "MEMBERS", "timeframe": "DAILY",
            "entry": {"all": entry}, "exit": {"any": exit_}, "ranking": {"feature": "ret_252d", "order": "DESC"},
            "position": {"max_positions": POSITIONS, "sizing": "EQUAL_WEIGHT"}, "risk": {"max_position_percent": 10}, "rebalance": "MONTHLY",
        }
    )  # fmt: skip


def definitions() -> list[StrategyDef]:
    top = {"feature": "ret_252d", "op": "TOP_PERCENT", "value": ENTRY_SHARE}
    weak = {"feature": "ret_252d", "op": "BOTTOM_PERCENT", "value": EXIT_SHARE}
    return [
        _def(
            "MOMENTUM_12M_M",
            f"Hold the strongest {ENTRY_SHARE}% of stocks by 12-month return each month; sell when one falls into the weakest {EXIT_SHARE}%.",
            [top],
            [weak],
        ),
        _def(
            "MOMENTUM_LOWVOL_M",
            f"12-month momentum among the calmer {CALM_SHARE}% of stocks by 60-day volatility.",
            [top, {"feature": "vol_60d", "op": "BOTTOM_PERCENT", "value": CALM_SHARE}],
            [weak],
        ),
        _def(
            "MOMENTUM_TREND_M",
            f"12-month momentum with a market filter: no new buys while under {MARKET_IN}% of stocks are above their 200-day average; everything is sold under {MARKET_OUT}%.",
            [top, {"feature": MARKET_BREADTH, "op": ">=", "value": MARKET_IN}],
            [weak, {"feature": MARKET_BREADTH, "op": "<", "value": MARKET_OUT}],
        ),
    ]


def register_all(conn: psycopg.Connection, *, by: str, now: datetime) -> list[str]:
    """Register each definition once (insert-only registry); returns the ids written this time. Running it again writes nothing."""
    written = []
    for d in definitions():
        if registry.versions(conn, d.strategy_id):
            continue
        registry.register(
            conn,
            d,
            by=by,
            reason="pre-registered from published research before any result (review 2026-11-16, section 3.7)",
            now=now,
        )
        written.append(d.strategy_id)
    return written
