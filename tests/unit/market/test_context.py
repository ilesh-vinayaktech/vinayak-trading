import pytest

from algo.market import context


def _line(n: int, start: float, step: float) -> list[float]:
    return [start + step * i for i in range(n)]


def test_ret_needs_history_and_a_positive_base():
    assert context.ret([100.0, 110.0], 1) == pytest.approx(10.0)
    assert context.ret([100.0, 110.0], 2) is None
    assert context.ret([0.0, 5.0], 1) is None


def test_regime_up_down_sideways_and_too_short():
    assert context.regime([1.0] * 209) is None
    assert context.regime(_line(260, 100, 1.0)) == "uptrend"
    assert context.regime(_line(260, 400, -1.0)) == "downtrend"
    # a long rise, then one bar far under the 50-day while that average still rises: neither up nor down
    assert context.regime(_line(259, 100, 1.0) + [100.0]) == "sideways"


def test_adx_is_high_in_a_steady_trend_low_in_chop_and_none_when_short():
    n = 120
    up = _line(n, 100, 1.0)
    strong = context.adx([c + 0.5 for c in up], [c - 0.5 for c in up], up)
    chop = [100.0 + (2 if i % 2 else -2) for i in range(n)]
    weak = context.adx([c + 0.5 for c in chop], [c - 0.5 for c in chop], chop)
    assert strong is not None and weak is not None and strong > 25 > 15 > weak
    assert context.adx([1.0] * 10, [1.0] * 10, [1.0] * 10) is None
    flat = [100.0] * n
    assert context.adx(flat, flat, flat) == 0.0  # no range at all: no trend, no division by zero


def test_adx_label_bands():
    assert context.adx_label(None) is None
    assert [context.adx_label(v) for v in (30, 20, 10)] == [
        "strong trend",
        "moderate trend",
        "no trend",
    ]


def test_ema_trend():
    assert context.ema_trend([1.0] * 49) is None
    assert context.ema_trend(_line(80, 100, 1.0)) == "above"
    assert context.ema_trend(_line(80, 200, -1.0)) == "below"


def test_sector_view_uses_medians_and_a_neutral_band():
    assert context.sector_view([], [1.0]) is None
    assert context.sector_view([1.0], []) is None
    assert context.sector_view([1.0, 3.0, 50.0], [0.0, 0.5, 1.0]) == (
        3.0,
        0.5,
        "outperforming",
    )  # the 50.0 outlier does not drag the median
    assert context.sector_view([-2.0], [0.0, 0.0]) == (-2.0, 0.0, "underperforming")
    assert context.sector_view([0.3], [0.0]) == (0.3, 0.0, "in line")


def test_breakout_facts_exclude_the_candle_being_judged_and_say_none_without_history():
    highs = [100.0] * 25
    closes = [99.0] * 24 + [100.0]  # today's close equals the prior 20-day high: not above it
    f = context.breakout_facts(highs, [95.0] * 25, closes)
    assert f["above_20d_high"] is False and f["high_20d"] == 100.0 and f["breakout"] == "none"
    closes = [99.0] * 24 + [100.5]
    highs = [100.0] * 24 + [101.0]  # today's own high must not raise the bar it is judged against
    f = context.breakout_facts(highs, [95.0] * 25, closes)
    assert (
        f["above_20d_high"] is True and f["breakout"] == "crossed today" and f["high_20d"] == 100.0
    )
    closes2 = [99.0] * 23 + [100.5, 101.5]
    highs2 = [100.0] * 23 + [100.8, 102.0]
    f = context.breakout_facts(highs2, [95.0] * 25, closes2)
    assert (
        f["breakout"] == "already above"
    )  # yesterday's close was over its own prior 20-day high too
    short = context.breakout_facts([1.0] * 20, [1.0] * 20, [1.0] * 20)
    assert all(
        v is None for v in short.values()
    )  # 20 candles: no 20-day reference yet, nothing is invented
    assert (
        context.breakout_facts([1.0] * 21, [1.0] * 21, [1.0] * 21)["breakout"] is None
    )  # no previous candle to compare with


def test_breakout_facts_52_week_high_needs_200_candles_and_extension_is_signed_in_atr():
    up = _line(260, 100, 1.0)
    f = context.breakout_facts([c + 0.5 for c in up], [c - 0.5 for c in up], up)
    assert (
        f["new_52w_high"] is True and f["high_52w"] == up[-2] + 0.5 and f["above_20d_high"] is True
    )
    assert f["extension_atr"] is not None and f["extension_atr"] > 0
    down = _line(260, 400, -1.0)
    d = context.breakout_facts([c + 0.5 for c in down], [c - 0.5 for c in down], down)
    assert d["new_52w_high"] is False and d["extension_atr"] is not None and d["extension_atr"] < 0
    few = context.breakout_facts([c + 0.5 for c in up[:150]], [c - 0.5 for c in up[:150]], up[:150])
    assert (
        few["new_52w_high"] is None and few["high_52w"] is None and few["extension_atr"] is not None
    )
    flat = [100.0] * 60
    assert (
        context.breakout_facts(flat, flat, flat)["extension_atr"] is None
    )  # no range: no ATR, no division by zero
