from decimal import Decimal as D

import pytest

from algo.indicators import core


def d(*xs):
    return [None if x is None else D(str(x)) for x in xs]


def near(got, want, places=4):
    assert len(got) == len(want)
    for g, w in zip(got, want, strict=True):
        if w is None:
            assert g is None
        else:
            assert g is not None and abs(g - D(str(w))) < D(10) ** -places, (g, w)


def test_sma_waits_for_a_full_window_and_skips_leading_gaps():
    near(core.sma(d(1, 2, 3, 4, 5), 3), [None, None, 2, 3, 4])
    near(
        core.sma(d(None, None, 3, 4, 5, 6), 3), [None, None, None, None, 4, 5]
    )  # starts at the first value
    assert core.sma(d(None, None), 2) == [None, None]
    assert core.sma(d(1, 2), 0) == [None, None]
    near(
        core.sma(d(1, None, 3, 4, 5), 2), [None, None, None, 3.5, 4.5]
    )  # a gap inside breaks the window


def test_ema_is_seeded_with_the_sma_then_recursive():
    near(core.ema(d(1, 2, 3, 4, 5), 3), [None, None, 2, 3, 4])  # alpha = 0.5
    near(core.ema(d(None, 10, 20, 30, 40), 2), [None, None, 15, 25, 35])  # alpha = 2/3
    near(
        core.ema(d(1, 2, 3, None, 5), 3), [None, None, 2, None, 3.5]
    )  # a gap leaves that bar empty


def test_rma_is_wilders_smoothing():
    near(core.rma(d(1, 2, 3, 4, 5), 3), [None, None, 2, 2.66666667, 3.44444444])


def test_wma_weights_recent_values_most():
    near(core.wma(d(1, 2, 3, 4), 3), [None, None, 2.33333333, 3.33333333])  # (1+4+9)/6, (2+6+12)/6
    assert core.wma(d(None), 1) == [None]
    assert core.wma(d(1, 2), 0) == [None, None]
    near(core.wma(d(1, None, 3, 4), 2), [None, None, None, 3.66666667])


def test_stdev_is_the_population_deviation():
    near(core.stdev(d(1, 2, 3), 3), [None, None, 0.81649658])
    near(core.stdev(d(5, 5, 5), 3), [None, None, 0])


def test_windows_true_range_and_change():
    h, lo, c = d(10, 12, 11), d(8, 9, 7), d(9, 11, 8)
    assert core.highest(h, 2) == [None, D(12), D(12)]
    assert core.lowest(lo, 2) == [None, D(8), D(7)]
    near(core.true_range(h, lo, c), [2, 3, 4])  # bar 3: max(4, |11-11|, |7-11|) = 4
    assert core.change(d(1, 3, 2)) == [None, D(2), D(-1)]


def test_the_golden_inputs_are_decimals_not_floats():
    assert all(isinstance(v, D) for v in core.sma(d(1, 2, 3), 2) if v is not None)
    with pytest.raises(TypeError):
        core.sma([1.5, 2.5], 2)  # type: ignore[list-item]  # floats are refused by the Decimal arithmetic


def test_the_last_average_alone_is_exactly_the_last_value_of_the_whole_series():
    import random

    rng = random.Random(7)
    for _ in range(300):
        n = rng.randint(1, 12)
        x = [
            None if rng.random() < 0.15 else D(str(round(rng.uniform(1, 500), rng.randint(0, 6))))
            for _ in range(rng.randint(0, 40))
        ]
        assert core.sma_last(x, n) == (core.sma(x, n)[-1] if x else None), (n, x)


def test_the_last_average_is_none_when_the_window_is_short_has_a_gap_or_the_series_is_empty():
    assert core.sma_last([], 3) is None
    assert core.sma_last(d(1, 2), 3) is None  # fewer values than the window
    assert core.sma_last(d(1, None, 3, 4), 3) is None  # a gap inside the last window
    assert core.sma_last(d(None, None, 1, 2, 3), 3) == D(
        2
    )  # warm-up Nones before the window do not matter
    assert core.sma_last(d(1, 2, 3), 0) is None
    assert core.sma_last([None, None], 2) is None
