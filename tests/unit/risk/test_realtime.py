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


# ---- found by mutation testing: the words of each breach and flag, and the one-unit boundaries ----------------------
def test_each_breach_says_in_exact_words_what_happened():
    lim = Limits(max_daily_loss=D(1000), max_drawdown=D("0.1"), max_data_age_s=D(60))
    live = Live(
        day_pnl=D(-1500),
        equity=D(80000),
        peak_equity=D(100000),
        data_age_s=D(90),
        broker_connected=False,
    )
    assert [(b.failure, b.detail) for b in monitor(live, lim)] == [
        (Failure.DAILY_LOSS, "today's loss 1500 has reached 1000"),
        (Failure.DRAWDOWN, "equity is 20.00% below its peak (limit 10.00%)"),
        (Failure.DATA_STALE, "no fresh data for 90 s (limit 60)"),
        (Failure.BROKER_DOWN, "the broker connection is down"),
    ]
    never = Live(
        day_pnl=D(0), equity=D(1), peak_equity=D(1), data_age_s=None, broker_connected=True
    )
    assert [b.detail for b in monitor(never, Limits(max_data_age_s=D(60)))] == [
        "no fresh data for None s (limit 60)"
    ]


def test_a_peak_of_exactly_one_is_still_measured_for_drawdown():
    lim = Limits(max_drawdown=D("0.5"))
    assert [b.failure for b in monitor(Live(D(0), D("0.5"), D(1), None, True), lim)] == [
        Failure.DRAWDOWN
    ]
    assert (
        monitor(Live(D(0), D(0), D(0), None, True), lim) == []
    )  # no peak: nothing to measure against


def test_post_trade_flags_say_what_was_realised_and_a_fill_rate_exactly_at_the_floor_passes():
    lim = Limits(slippage_tolerance=D(2), min_fill_rate=D("0.9"))
    fills = [Fill(Side.BUY, 10, D(100), D("100.10"))]  # 10 bps worse
    assert [
        (f.code, f.detail) for f in post_trade(fills, ordered_qty=10, model_bps=D(4), limits=lim)
    ] == [("SLIPPAGE", "realised 10.0 bps against the model's 4 bps")]
    assert [
        (f.code, f.detail)
        for f in post_trade(
            [Fill(Side.BUY, 8, D(100), D(100))], ordered_qty=10, model_bps=D(4), limits=lim
        )
    ] == [("FILL_RATE", "8 of 10 shares filled, below 90%")]
    nine_of_ten = [Fill(Side.BUY, 9, D(100), D(100))]
    assert (
        post_trade(nine_of_ten, ordered_qty=10, model_bps=D(4), limits=lim) == []
    )  # 0.9 is not below 0.9
    assert [f.code for f in post_trade([], ordered_qty=1, model_bps=D(4), limits=lim)] == [
        "FILL_RATE"
    ]  # a single share ordered and none filled


def test_a_long_position_is_stopped_exactly_at_two_percent_by_default():
    from algo.risk.realtime import OpenPosition, trade_stops

    lim = Limits()
    assert lim.max_trade_loss == D("0.02")
    just_inside = OpenPosition(1, 10, D(100), D("98.01"))
    at_limit = OpenPosition(2, 10, D(100), D(98))
    assert trade_stops([just_inside], lim) == []
    (stop,) = trade_stops([at_limit], lim)
    assert (stop.instrument_id, stop.loss) == (2, D("0.02"))
    assert "long 10 is 2.00% against its entry 100 (limit 2.00%)" == stop.detail


def test_a_short_is_stopped_when_the_price_rises_and_a_winner_never_is():
    from algo.risk.realtime import OpenPosition, trade_stops

    lim = Limits()
    short_hit = OpenPosition(3, -5, D(200), D(204))
    short_ok = OpenPosition(4, -5, D(200), D("203.99"))
    long_win = OpenPosition(5, 5, D(100), D(150))
    short_win = OpenPosition(6, -5, D(100), D(50))
    out = trade_stops([short_hit, short_ok, long_win, short_win], lim)
    assert [s.instrument_id for s in out] == [3] and out[0].detail.startswith("short 5 is 2.00%")


def test_the_limit_can_be_changed_or_switched_off_and_bad_prices_are_refused():
    import pytest

    from algo.risk.realtime import OpenPosition, trade_stops

    p = OpenPosition(1, 10, D(100), D(95))
    assert trade_stops([p], Limits(max_trade_loss=D("0.05")))[0].loss == D("0.05")
    assert trade_stops([p], Limits(max_trade_loss=D("0.06"))) == []
    assert trade_stops([p], Limits(max_trade_loss=None)) == []
    assert trade_stops([OpenPosition(1, 0, D(100), D(1))], Limits()) == []  # flat: nothing to stop
    for bad in (
        OpenPosition(1, 1, D(0), D(1)),
        OpenPosition(1, 1, D(1), D(0)),
        OpenPosition(1, 1, D(-1), D(1)),
    ):
        with pytest.raises(ValueError, match="prices must be positive"):
            trade_stops([bad], Limits())
    assert Limits.from_mapping({"max_trade_loss": "0.03"}).max_trade_loss == D("0.03")


def test_one_share_positions_a_price_of_one_and_a_flat_position_before_a_real_stop():
    from algo.risk.realtime import OpenPosition, trade_stops

    flat_first = [
        OpenPosition(1, 0, D(100), D(1)),
        OpenPosition(2, 1, D(100), D(90)),
        OpenPosition(3, -1, D(100), D(110)),
    ]
    out = trade_stops(flat_first, Limits())
    assert [(s.instrument_id, s.detail[:6]) for s in out] == [(2, "long 1"), (3, "short ")]
    assert trade_stops([OpenPosition(4, 5, D(1), D("0.97"))], Limits())[0].loss == D(
        "0.03"
    )  # a stock priced at 1 is fine
