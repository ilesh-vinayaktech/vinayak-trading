from datetime import date
from decimal import Decimal as D

import pytest

from algo.backtest.costs.policy import CostModel, Liquidity
from algo.backtest.costs.scaled import ScaledCosts

LIQ = Liquidity(volume=D(1000), range_bps=D(100), adv_value=None)
BASE = CostModel("flat", D(10), D(5), True)
DAY = date(2024, 1, 2)


def test_charges_and_slippage_scale_by_the_factor_and_nothing_else_changes():
    s = ScaledCosts(BASE, D(2))
    assert (
        s.charges(DAY, "BUY", D(10), D(100)).total
        == 2 * BASE.charges(DAY, "BUY", D(10), D(100)).total
    )
    px, bps = s.fill("BUY", D(100), D(10), LIQ)
    assert bps == D(10) and px == D(100) * (1 + D(10) / 10000)
    px, bps = s.fill("SELL", D(100), D(10), LIQ)
    assert px == D(100) * (1 - D(10) / 10000)
    assert s.name == "flatx2" and s.placeholder is True and s.zero_slippage is False
    assert s.note_shortfall(DAY, D(5)) == 0
    assert s.describe()["stress_factor"] == "2" and s.describe()["kind"] == "flat_bps"


def test_a_factor_of_one_is_the_identity_and_zero_or_negative_is_refused():
    one = ScaledCosts(BASE, D(1))
    assert one.fill("BUY", D(100), D(10), LIQ) == BASE.fill("BUY", D(100), D(10), LIQ)
    for bad in (D(0), D(-1)):
        with pytest.raises(ValueError, match="^cost factor must be positive$"):
            ScaledCosts(BASE, bad)


def test_shortfall_is_scaled_too():
    class Short(CostModel):
        def note_shortfall(self, day, brokerage_total):
            return D(3)

    assert ScaledCosts(Short("s", D(0), D(0), False), D(2)).note_shortfall(DAY, D(0)) == 6
