from decimal import Decimal as D

import pytest

from algo.backtest.costs.slippage import SlippageModel, fill_price, slippage_bps

M = SlippageModel(
    base_bps=D(5),
    participation_bps_per_pct=D(2),
    volatility_fraction=D("0.1"),
    illiquid_adv_threshold=D(10_000_000),
    illiquid_extra_bps=D(10),
    max_bps=D(100),
)


def test_each_term_hand_computed():
    # 5 base + 3% participation x 2 bps/pct = 6 + 0.1 x 200 bps range = 20 ; liquid => no surcharge
    assert slippage_bps(M, participation=D("0.03"), range_bps=D(200), adv_value=D(50_000_000)) == D(
        31
    )
    # illiquid (adv below threshold) adds 10
    assert slippage_bps(M, participation=D("0.03"), range_bps=D(200), adv_value=D(5_000_000)) == D(
        41
    )
    # unknown liquidity is treated as illiquid, never as liquid
    assert slippage_bps(M, participation=D("0.03"), range_bps=D(200), adv_value=None) == D(41)


def test_the_threshold_itself_counts_as_liquid():
    assert slippage_bps(M, participation=D(0), range_bps=D(0), adv_value=D(10_000_000)) == D(5)


def test_the_cap_applies():
    assert slippage_bps(M, participation=D("1"), range_bps=D(5000), adv_value=None) == D(100)


def test_no_illiquidity_rule_means_no_surcharge():
    m = SlippageModel(base_bps=D(5), illiquid_extra_bps=D(10))
    assert slippage_bps(m, participation=D(0), range_bps=D(0), adv_value=None) == D(5)


def test_buys_fill_above_and_sells_below_the_reference():
    assert fill_price(D(100), "BUY", D(50)) == D("100.5")
    assert fill_price(D(100), "SELL", D(50)) == D("99.5")
    assert fill_price(D(100), "BUY", D(0)) == D(100)
    with pytest.raises(ValueError, match="^side must be BUY or SELL$"):
        fill_price(D(100), "X", D(1))


def test_the_zero_model_is_recognised_so_validation_can_refuse_it():
    assert SlippageModel().is_zero
    assert not SlippageModel(base_bps=D(1)).is_zero
    assert not SlippageModel(participation_bps_per_pct=D(1)).is_zero
    assert not SlippageModel(volatility_fraction=D("0.1")).is_zero
    assert not SlippageModel(illiquid_extra_bps=D(1)).is_zero


@pytest.mark.parametrize(
    "field",
    [
        "base_bps",
        "participation_bps_per_pct",
        "volatility_fraction",
        "illiquid_extra_bps",
        "max_bps",
    ],
)
def test_negative_parameters_are_rejected(field):
    with pytest.raises(ValueError, match="^slippage parameters cannot be negative$"):
        SlippageModel(**{field: D(-1)})
