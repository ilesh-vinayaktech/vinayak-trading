import math
import random

import pytest

from algo.portfolio import regime as rg


def path(daily, n=300, start=100.0):
    out = [start]
    for i in range(n - 1):
        out.append(out[-1] * (1 + daily(i)))
    return out


def test_a_steady_rise_is_a_strong_bull_and_a_steady_fall_a_strong_bear():
    up = rg.classify(path(lambda i: 0.002))
    assert (
        up.trend == "STRONG_BULL" and up.detail["close"] > up.detail["sma50"] > up.detail["sma200"]
    )
    down = rg.classify(path(lambda i: -0.002))
    assert (
        down.trend == "STRONG_BEAR"
        and down.detail["close"] < down.detail["sma50"] < down.detail["sma200"]
    )


def test_a_dip_inside_an_uptrend_and_a_bounce_inside_a_downtrend_are_the_weak_labels():
    dip = path(
        lambda i: 0.003 if i < 280 else -0.01
    )  # rose 270 days, then fell: below the 50-day, above the 200-day
    r = rg.classify(dip)
    assert (
        r.detail["close"] > r.detail["sma200"]
        and r.detail["close"] < r.detail["sma50"]
        and r.trend == "WEAK_BULL"
    )
    bounce = path(lambda i: -0.003 if i < 280 else 0.01)
    b = rg.classify(bounce)
    assert (
        b.detail["close"] < b.detail["sma200"]
        and b.detail["close"] > b.detail["sma50"]
        and b.trend == "WEAK_BEAR"
    )


def test_flat_prices_around_the_long_average_are_sideways():
    flat = path(lambda i: 0.0005 * math.sin(i / 5), n=300)
    assert rg.classify(flat).trend == "SIDEWAYS"
    s = [100.0] * 300
    assert rg.classify(s).trend == "SIDEWAYS"  # exactly on the average


def test_too_little_history_is_unknown_not_a_guess():
    r = rg.classify(path(lambda i: 0.001, n=199))
    assert (r.trend, r.volatility, r.detail) == ("UNKNOWN", "UNKNOWN", {})
    mid = rg.classify(path(lambda i: 0.001, n=271))  # enough for trend, 1 short for volatility
    assert mid.trend != "UNKNOWN" and mid.volatility == "UNKNOWN"
    assert rg.classify(path(lambda i: 0.001, n=272)).volatility != "UNKNOWN"


def calm_then(shock_vol, calm_vol=0.004, n=400, shock_days=20, seed=1):
    rng = random.Random(seed)
    rets = [rng.gauss(0, calm_vol) for _ in range(n - shock_days)] + [
        rng.gauss(0, shock_vol) for _ in range(shock_days)
    ]
    return path(lambda i: rets[i - 1] if i else 0, n=n + 1)[:n]


def test_volatility_is_ranked_against_its_own_last_year():
    assert (
        rg.classify(calm_then(0.03)).volatility == "HIGH"
    )  # a violent last month after a quiet year
    quiet_now = rg.classify(calm_then(0.0005, calm_vol=0.01))
    assert quiet_now.volatility == "LOW"
    same = rg.classify(calm_then(0.004, seed=4))
    assert same.volatility == "NORMAL" and 0.2 < same.detail["vol_percentile"] < 0.8


def test_the_regime_uses_only_the_closes_it_is_given():
    p = path(lambda i: 0.002, n=300)
    assert (
        rg.classify(p[:280]).detail["close"] == p[279]
    )  # an earlier day's regime does not see later closes


def test_bad_prices_are_refused():
    for bad in (-1.0, 0.0, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="positive"):
            rg.classify([100.0] * 299 + [bad])


def test_exact_averages_volatility_and_boundaries():
    import statistics

    ramp = [float(i) for i in range(1, 301)]
    r = rg.classify(ramp)
    assert r.detail["sma50"] == pytest.approx(275.5) and r.detail["sma200"] == pytest.approx(
        200.5
    )  # means of the last 50 and 200
    assert (
        rg.classify([float(i) for i in range(1, 201)]).trend != "UNKNOWN"
    )  # exactly 200 closes is enough
    wiggly = path(lambda i: 0.01 * math.sin(i * 1.7) + 0.002, n=300)
    closes = wiggly
    last = [b / a - 1 for a, b in zip(closes[-21:-1], closes[-20:], strict=True)]
    assert rg.classify(closes).detail["vol_20d"] == pytest.approx(statistics.stdev(last))
    assert rg.classify([0.5] * 299 + [0.5]).trend == "SIDEWAYS"  # prices under 1 are fine
    flat = rg.classify([100.0] * 300)
    assert flat.volatility == "NORMAL" and flat.detail["vol_20d"] == 0.0


def test_sideways_needs_both_the_close_and_the_50_day_to_hug_the_long_average():
    step = [100.0] * 150 + [
        102.5
    ] * 50  # close within 2% of the 200-day, the 50-day is not within 1%
    r = rg.classify(step)
    assert (
        r.trend == "WEAK_BULL" and r.detail["close"] == r.detail["sma50"]
    )  # equal to the 50-day is not above it
    spike = [100.0] * 299 + [110.0]  # the 50-day hugs the 200-day, the close is 10% away
    assert rg.classify(spike).trend == "STRONG_BULL"
    small = [100.0] * 299 + [103.0]  # 3% away
    assert rg.classify(small).trend == "STRONG_BULL"
    with pytest.raises(ValueError, match="^closes must be positive numbers$"):
        rg.classify([0.0] * 300)
