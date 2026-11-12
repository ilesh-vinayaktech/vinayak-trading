"""The strategies the platform can run, by id: the class and its parameter model.

Paper trading and backtest studies both look strategies up here: a new one is added once."""

from __future__ import annotations

from algo.strategies.trend_pullback import TrendPullback, TrendPullbackParams

STRATEGIES = {"trend_pullback": (TrendPullback, TrendPullbackParams)}
