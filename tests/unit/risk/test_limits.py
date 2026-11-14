from datetime import time
from decimal import Decimal as D

import pytest

from algo.risk.limits import Limits, LimitsError


def test_nothing_is_limited_by_default():
    assert Limits() == Limits.from_mapping({})
    assert Limits().allowed is None and Limits().max_order_value is None


def test_limits_load_from_plain_config_values():
    lim = Limits.from_mapping(
        {
            "allowed": [1, 2],
            "restricted": ["3"],
            "max_order_qty": "100",
            "max_order_value": "50000.50",
            "order_rate_per_s": 5,
            "order_burst": "10",
            "trading_hours": ["09:15", "15:30"],
            "max_daily_loss": "2500",
            "check_margin": True,
            "max_drawdown": "0.1",
        }
    )
    assert lim.allowed == frozenset({1, 2}) and lim.restricted == frozenset({3})
    assert (lim.max_order_qty, lim.order_burst) == (100, 10)
    assert lim.max_order_value == D("50000.50") and lim.order_rate_per_s == D(5)
    assert lim.trading_hours == (time(9, 15), time(15, 30)) and lim.max_daily_loss == D(2500)
    assert lim.check_margin is True and lim.max_drawdown == D("0.1")


def test_an_unknown_key_is_refused_not_ignored():
    with pytest.raises(LimitsError, match="unknown limit.*max_order_valu"):
        Limits.from_mapping({"max_order_valu": 1})
