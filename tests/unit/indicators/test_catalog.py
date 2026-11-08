import random
from decimal import Decimal as D

import pytest

from algo.indicators.catalog import CATALOG, Bars, IndicatorError, compute, parse_spec


def bars(close, high=None, low=None, volume=None, open_=None):
    c = [D(str(x)) for x in close]
    h = [D(str(x)) for x in high] if high else c
    lo = [D(str(x)) for x in low] if low else c
    v = [D(str(x)) for x in volume] if volume else [D(1000)] * len(c)
    o = [D(str(x)) for x in open_] if open_ else c
    return Bars(o, h, lo, c, v)


def run(spec, b):
    return compute(spec, b)[2]


def f(series):
    return [None if v is None else round(float(v), 4) for v in series]


# Wilder's classic RSI example (as in the StockCharts worksheet). The published values round the
# running averages to two decimals, so ours agree with them to within a few hundredths.
CLOSES = "44.34 44.09 44.15 43.61 44.33 44.83 45.10 45.42 45.84 46.08 45.89 46.03 45.61 46.28 46.28 46.00 46.03 46.41 46.22 45.64 46.21 46.25 45.71 46.45 45.78 45.35 44.03 44.18 44.22 44.57 43.42 42.66 43.13".split()
PUBLISHED = [
    70.53,
    66.32,
    66.55,
    69.41,
    66.36,
    57.97,
    62.93,
    63.26,
    56.06,
    62.38,
    54.71,
    50.42,
    39.99,
    41.46,
    41.87,
    45.46,
    37.30,
    33.08,
    37.77,
]


def test_rsi_matches_wilders_published_example_and_an_independent_calculation():
    b = bars(CLOSES)
    rsi = run("rsi:14", b)["value"]
    assert all(v is None for v in rsi[:14])
    got = [float(v) for v in rsi[14:] if v is not None]
    assert len(got) == len(PUBLISHED)
    assert max(abs(g - p) for g, p in zip(got, PUBLISHED, strict=True)) < 0.1
    # independent: exact Wilder recursion written out longhand
    c = [float(x) for x in CLOSES]
    gains = [max(c[i] - c[i - 1], 0) for i in range(1, len(c))]
    losses = [max(c[i - 1] - c[i], 0) for i in range(1, len(c))]
    ag, al = sum(gains[:14]) / 14, sum(losses[:14]) / 14
    expected = [100 - 100 / (1 + ag / al)]
    for i in range(14, len(gains)):
        ag, al = (ag * 13 + gains[i]) / 14, (al * 13 + losses[i]) / 14
        expected.append(100 - 100 / (1 + ag / al))
    assert max(abs(g - e) for g, e in zip(got, expected, strict=True)) < 1e-9


def test_rsi_edges():
    assert f(run("rsi:3", bars([1, 2, 3, 4, 5, 6]))["value"])[3:] == [
        100.0,
        100.0,
        100.0,
    ]  # only gains
    assert f(run("rsi:3", bars([6, 5, 4, 3, 2, 1]))["value"])[3:] == [0.0, 0.0, 0.0]  # only losses
    assert f(run("rsi:3", bars([5, 5, 5, 5, 5, 5]))["value"])[3:] == [
        100.0,
        100.0,
        100.0,
    ]  # Pine: no losses reads 100


def test_moving_averages_through_the_catalogue():
    b = bars([1, 2, 3, 4, 5])
    assert f(run("sma:3", b)["value"]) == [None, None, 2, 3, 4]
    assert f(run("ema:3", b)["value"]) == [None, None, 2, 3, 4]
    assert f(run("wma:3", b)["value"]) == [None, None, 2.3333, 3.3333, 4.3333]


def test_bollinger_bands_are_basis_plus_minus_population_deviations():
    r = run("bb:3:2", bars([1, 2, 3]))
    assert f(r["basis"]) == [None, None, 2.0]
    assert f(r["upper"]) == [None, None, 3.633]
    assert f(r["lower"]) == [None, None, 0.367]
    flat = run("bb:3:2", bars([5, 5, 5]))
    assert f(flat["upper"]) == f(flat["lower"]) == [None, None, 5.0]


def test_macd_of_a_constant_series_is_zero_and_of_a_rise_is_positive():
    flat = run("macd:3:6:2", bars([10] * 20))
    assert f(flat["macd"])[5] == 0.0 and f(flat["hist"])[-1] == 0.0
    up = run("macd:3:6:2", bars(list(range(1, 31))))
    assert up["macd"][-1] > 0 and up["signal"][-1] is not None
    assert f(up["hist"])[-1] == round(
        float(up["macd"][-1] - up["signal"][-1]), 4
    )  # histogram = macd - signal
    assert up["signal"][5] is None  # the signal needs its own warm-up after the MACD line starts


def test_stochastic_position_in_the_range():
    top = run("stoch:3:2:1", bars([1, 2, 3, 4, 5], high=[1, 2, 3, 4, 5], low=[1, 2, 3, 4, 5]))
    assert f(top["k"])[2:] == [100.0, 100.0, 100.0] and f(top["d"])[3:] == [100.0, 100.0]
    flat = run("stoch:3:1:1", bars([5, 5, 5, 5]))
    assert f(flat["k"])[2:] == [50.0, 50.0]  # a flat range reads the middle, not a division by zero
    mid = run("stoch:3:1:1", bars([2, 3, 2], high=[3, 4, 3], low=[1, 2, 1]))
    assert f(mid["k"])[2] == 33.3333  # (2-1)/(4-1)


def test_atr_and_williams_and_obv_and_cci():
    b = bars([10, 11, 12, 13], high=[11, 12, 13, 14], low=[9, 10, 11, 12])
    assert f(run("atr:2", b)["value"]) == [None, 2.0, 2.0, 2.0]  # a steady 2-wide bar with no gaps
    assert f(run("willr:3", bars([1, 2, 3, 4]))["value"])[2:] == [0.0, 0.0]  # closing at the high
    assert f(run("willr:3", bars([4, 3, 2, 1]))["value"])[2:] == [
        0.0 - 100.0,
        -100.0,
    ]  # closing at the low
    assert f(run("willr:3", bars([5, 5, 5, 5]))["value"])[2:] == [-50.0, -50.0]
    obv = run("obv", bars([10, 11, 11, 9], volume=[100, 200, 300, 400]))["value"]
    assert [int(v) for v in obv if v is not None] == [0, 200, 200, -200]
    assert f(run("cci:3", bars([5, 5, 5, 5]))["value"])[2:] == [
        0.0,
        0.0,
    ]  # no deviation: zero, not a division
    cci = run("cci:3", bars([1, 2, 6]))["value"][2]
    assert (
        cci is not None and round(float(cci), 2) == 100.0
    )  # tp 1,2,6: mean 3, mean deviation 2: (6-3)/(0.015*2)


def test_adx_separates_a_trend_from_a_flat_market():
    n = 60
    up = bars(
        [100 + i for i in range(n)],
        high=[101 + i for i in range(n)],
        low=[99 + i for i in range(n)],
    )
    r = run("adx:5:5", up)
    assert r["plus"][-1] > r["minus"][-1] and r["adx"][-1] > 50
    down = run(
        "adx:5:5",
        bars(
            [200 - i for i in range(n)],
            high=[201 - i for i in range(n)],
            low=[199 - i for i in range(n)],
        ),
    )
    assert down["minus"][-1] > down["plus"][-1]
    flat = run("adx:5:5", bars([10] * n))
    assert all(v is None for v in flat["adx"])  # zero true range: undefined, not a division by zero
    inside = bars(
        [10, 10, 10, 10, 10, 10, 10, 10],
        high=[12, 11, 11, 11, 11, 11, 11, 11],
        low=[8, 9, 9, 9, 9, 9, 9, 9],
    )
    assert (
        run("adx:2:2", inside)["adx"][-1] is not None
    )  # +DM = -DM = 0 while the range is not: the sum guard
    assert f(run("adx:2:2", inside)["plus"])[-1] == 0.0


def test_parabolic_sar_sits_below_a_rise_and_flips_above_after_a_reversal():
    close = [10, 11, 12, 13, 14, 15, 14, 12, 10, 8, 6, 5, 6, 8, 10, 12]
    high = [c + 0.5 for c in close]
    low = [c - 0.5 for c in close]
    sar = run("psar:0.02:0.02:0.2", bars(close, high=high, low=low))["value"]
    assert all(v is not None for v in sar)
    assert sar[3] < low[3] and sar[4] < low[4]  # rising: the dots trail below
    first_above = next(i for i in range(5, len(close)) if sar[i] > high[i])
    assert 6 <= first_above <= 9  # it flipped to a downtrend soon after the peak
    assert sar[10] > high[10]
    assert any(
        sar[i] < low[i] for i in range(12, len(close))
    )  # and flipped back up on the recovery
    assert sar[0] == D("9.5")  # the first dot is the first bar's low in an up start
    falling = run(
        "psar:0.02:0.02:0.2",
        bars([10, 9, 8, 7, 6], high=[10.5, 9.5, 8.5, 7.5, 6.5], low=[9.5, 8.5, 7.5, 6.5, 5.5]),
    )["value"]
    assert falling[0] == D("10.5") and falling[1] > D("8.5")  # a down start sits above the highs
    assert run("psar", bars([5]))["value"] == [None]  # one bar is not enough
    caps = run(
        "psar:0.5:0.5:0.6",
        bars(
            list(range(1, 15)),
            high=[i + 1 for i in range(1, 15)],
            low=[i - 1 for i in range(1, 15)],
        ),
    )["value"]
    assert caps[-1] is not None  # the acceleration factor stops at its maximum


def test_supertrend_flips_with_the_trend():
    close = [10 + i for i in range(20)] + [30 - 2 * i for i in range(20)]
    r = run("supertrend:3:2", bars(close, high=[c + 1 for c in close], low=[c - 1 for c in close]))
    assert r["up"][15] is not None and r["down"][15] is None  # rising: the stop trails below
    assert r["down"][-1] is not None and r["up"][-1] is None  # falling: it flipped above
    assert r["up"][0] is None and r["down"][0] is None  # ATR warm-up
    back = close + [c - 20 + 2 * i for i, c in enumerate(close[:20])]
    rr = run("supertrend:3:2", bars(back, high=[c + 1 for c in back], low=[c - 1 for c in back]))
    assert rr["up"][-1] is not None  # and flipped back up on the recovery
    ratchet = run(
        "supertrend:2:1",
        bars(
            [10, 9, 8, 7, 8, 9, 10, 9, 8],
            high=[11, 10, 9, 8, 9, 10, 11, 10, 9],
            low=[9, 8, 7, 6, 7, 8, 9, 8, 7],
        ),
    )
    assert any(v is not None for v in ratchet["down"])


def test_specs_parse_defaults_positional_arguments_and_reject_nonsense():
    ind, params = parse_spec("rsi")
    assert ind.name == "rsi" and params == {"length": D(14)}
    assert parse_spec("macd:5:10")[1] == {"fast": D(5), "slow": D(10), "signal": D(9)}
    assert parse_spec("bb:20:2.5")[1]["mult"] == D("2.5")
    assert parse_spec("bb::3")[1] == {
        "length": D(20),
        "mult": D(3),
    }  # an empty argument keeps the default
    assert parse_spec(" sma : 5".replace(" ", ""))[1]["length"] == D(5)
    for bad, msg in [
        ("nope", "unknown indicator"),
        ("rsi:1:2", "at most 1 parameters"),
        ("rsi:abc", "must be a number"),
        ("rsi:NaN", "must be a whole number"),
        ("rsi:2.5", "must be a whole number"),
        ("rsi:0", "between"),
        ("rsi:9999", "between"),
        ("bb:20:0", "between"),
        ("obv:1", "at most 0"),
    ]:
        with pytest.raises(IndicatorError, match=msg):
            parse_spec(bad)


def test_every_indicator_is_consistent_with_its_own_description():
    rng = random.Random(7)
    price = 100.0
    close, high, low, vol = [], [], [], []
    for _ in range(150):
        price *= 1 + rng.uniform(-0.02, 0.02)
        close.append(round(price, 2))
        high.append(round(price * 1.01, 2))
        low.append(round(price * 0.99, 2))
        vol.append(rng.randint(1000, 9000))
    b = bars(close, high=high, low=low, volume=vol)
    assert set(CATALOG) == {
        "sma",
        "ema",
        "wma",
        "bb",
        "supertrend",
        "psar",
        "rsi",
        "macd",
        "stoch",
        "atr",
        "adx",
        "cci",
        "willr",
        "obv",
    }
    for name, ind in CATALOG.items():
        assert ind.pane in ("overlay", "pane") and ind.description and ind.label
        for prm in ind.params:
            assert prm.lo <= prm.default <= prm.hi, (name, prm.key)
        _, params, out = compute(name, b)
        assert set(out) == {o.key for o in ind.outputs}, name
        assert params == {p.key: p.default for p in ind.params}
        for key, series in out.items():
            assert len(series) == len(b), (name, key)
            assert any(v is not None for v in series), (name, key)
    # bounded oscillators stay in their range on random data
    for name, key, lo, hi in [
        ("rsi", "value", 0, 100),
        ("stoch", "k", 0, 100),
        ("willr", "value", -100, 0),
        ("adx", "adx", 0, 100),
    ]:
        vals = [float(v) for v in compute(name, b)[2][key] if v is not None]
        assert lo <= min(vals) and max(vals) <= hi, name
