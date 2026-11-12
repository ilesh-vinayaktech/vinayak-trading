from algo.strategies.registry import STRATEGIES
from algo.strategies.trend_pullback import TrendPullback, TrendPullbackParams


def test_the_pullback_strategy_is_registered_with_its_parameter_model():
    assert STRATEGIES["trend_pullback"] == (TrendPullback, TrendPullbackParams)
