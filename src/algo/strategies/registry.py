"""The strategies the platform can run, by id: the class and its parameter model.

Paper trading and backtest studies both look strategies up here: a new one is added once."""

from __future__ import annotations

from typing import Any

from algo.strategies.screener import ScreenerParams, ScreenerStrategy
from algo.strategies.trend_pullback import TrendPullback, TrendPullbackParams
from algo.strategy.base import StrategyParams

STRATEGIES: dict[str, tuple[Any, type[StrategyParams]]] = {
    "trend_pullback": (TrendPullback, TrendPullbackParams),
    "screener": (
        ScreenerStrategy,
        ScreenerParams,
    ),  # its screen comes from the study (StudySpec.screen)
}
