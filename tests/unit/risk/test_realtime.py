from decimal import Decimal as D

from algo.risk.killswitch import Failure
from algo.risk.limits import Limits
from algo.risk.model import Side
from algo.risk.realtime import Fill, Live, monitor, post_trade

OK = Live(
    day_pnl=D(0), equity=D(100000), peak_equity=D(100000), data_age_s=D(5), broker_connected=True
)


def failures(live, limits):
    return [b.failure for b in monitor(live, limits)]


def test_a_healthy_book_has_no_breach_and_unset_limits_check_nothing():
    lim = Limits(max_daily_loss=D(1000), max_drawdown=D("0.1"), max_data_age_s=D(60))
    assert failures(OK, lim) == [] and failures(
        Live(D(-(10**9)), D(1), D(10**9), D(10**9), False), Limits()
    ) == [Failure.BROKER_DOWN]  # the broker connection is always watched


def test_daily_loss_stops_exactly_at_the_limit():
    lim = Limits(max_daily_loss=D(1000))
    assert failures(Live(D("-999.99"), D(1), D(1), None, True), lim) == []
    assert failures(Live(D(-1000), D(1), D(1), None, True), lim) == [Failure.DAILY_LOSS]


def test_drawdown_is_measured_from_the_peak_and_stops_exactly_at_the_limit():
    lim = Limits(max_drawdown=D("0.1"))
    assert failures(Live(D(0), D(90001), D(100000), None, True), lim) == []
    assert failures(Live(D(0), D(90000), D(100000), None, True), lim) == [Failure.DRAWDOWN]
    assert (
        failures(Live(D(0), D(50), D(0), None, True), lim) == []
    )  # no peak yet: nothing to fall from


def test_data_that_is_too_old_or_missing_halts_and_the_age_boundary_is_exact():
    lim = Limits(max_data_age_s=D(60))
    assert failures(Live(D(0), D(1), D(1), D(60), True), lim) == []
    assert failures(Live(D(0), D(1), D(1), D("60.001"), True), lim) == [Failure.DATA_STALE]
    assert failures(Live(D(0), D(1), D(1), None, True), lim) == [
        Failure.DATA_STALE
    ]  # never heard: stale, not fine


def test_breaches_come_with_a_reason():
    (b,) = monitor(Live(D(-5), D(1), D(1), None, True), Limits(max_daily_loss=D(5)))
    assert b.failure is Failure.DAILY_LOSS and "5" in b.detail


def test_post_trade_flags_slippage_over_the_tolerance_and_a_low_fill_rate():
    lim = Limits(slippage_tolerance=D(2), min_fill_rate=D("0.9"))
    fills = [
        Fill(Side.BUY, 10, D(100), D("100.10")),
        Fill(Side.SELL, 10, D(100), D("99.90")),
    ]  # 10 bps worse, both
    assert [
        f.code for f in post_trade(fills, ordered_qty=20, model_bps=D(5), limits=lim)
    ] == []  # exactly 2 x 5
    assert [f.code for f in post_trade(fills, ordered_qty=20, model_bps=D(4), limits=lim)] == [
        "SLIPPAGE"
    ]
    assert [f.code for f in post_trade(fills, ordered_qty=23, model_bps=D(5), limits=lim)] == [
        "FILL_RATE"
    ]  # 20/23 < 0.9
    better = [Fill(Side.BUY, 10, D(100), D("99.90"))]  # price improvement is not slippage
    assert post_trade(better, ordered_qty=10, model_bps=D(1), limits=lim) == []
    assert (
        post_trade([], ordered_qty=0, model_bps=D(1), limits=lim) == []
    )  # nothing ordered, nothing to judge
    assert [
        f.code for f in post_trade(fills, ordered_qty=23, model_bps=D(5), limits=Limits())
    ] == []  # no min fill rate set
    assert [f.code for f in post_trade(fills, ordered_qty=20, model_bps=D(1), limits=Limits())] == [
        "SLIPPAGE"
    ]  # the 2x default
