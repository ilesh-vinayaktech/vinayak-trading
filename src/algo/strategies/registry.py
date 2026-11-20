"""The strategies the platform can run, by id: the class and its parameter model.

Paper trading and backtest studies both look strategies up here: a new one is added once."""

from __future__ import annotations

from typing import Any

from algo.strategies.dsl_study import DslParams, DslStudyStrategy
from algo.strategies.ema_macd_cross import EmaMacdCross, EmaMacdCrossParams
from algo.strategies.screener import ScreenerParams, ScreenerStrategy
from algo.strategies.trend_pullback import TrendPullback, TrendPullbackParams
from algo.strategies.trend_ride import TrendRide, TrendRideParams
from algo.strategy.base import StrategyParams

STRATEGIES: dict[str, tuple[Any, type[StrategyParams]]] = {
    "trend_pullback": (TrendPullback, TrendPullbackParams),
    "ema_macd_cross": (EmaMacdCross, EmaMacdCrossParams),
    "trend_ride": (TrendRide, TrendRideParams),
    "dsl": (
        DslStudyStrategy,
        DslParams,
    ),  # a registered strategy definition, locked in the study (StudySpec.definition)
    "screener": (
        ScreenerStrategy,
        ScreenerParams,
    ),  # its screen comes from the study (StudySpec.screen)
}
