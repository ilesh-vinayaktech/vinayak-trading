import numpy as np

from algo.market import range_evaluate as re


def data(n, model_noise, base_noise, seed=2):
    rng = np.random.default_rng(seed)
    y = np.exp(rng.normal(0, 0.4, n))
    return y + rng.normal(0, base_noise, n), y + rng.normal(0, model_noise, n), y


def test_nothing_is_computed_below_the_minimum_so_there_is_nothing_to_peek_at():
    base, model, y = data(499, 0.05, 0.3)
    assert re.primary_test(base, model, y, reps=200) == {"sessions": 499, "evaluated": False}


def test_a_model_with_clearly_smaller_errors_is_validated_and_a_tie_or_worse_is_not():
    base, model, y = data(600, 0.05, 0.3)
    got = re.primary_test(base, model, y, reps=400)
    assert got["evaluated"] and got["delta"] > 0 and got["low"] > 0 and got["validated"] is True
    tie = re.primary_test(base, base, y, reps=400)
    assert tie["delta"] == 0 and tie["validated"] is False
    worse = re.primary_test(model, base, y, reps=400)
    assert worse["delta"] < 0 and worse["validated"] is False


def test_segments_with_too_few_sessions_are_left_out():
    base, model, y = data(100, 0.05, 0.3)
    got = re.segment_mae(["low"] * 80 + ["high"] * 20, model, base, y)
    assert set(got) == {"low"} and got["low"][0] == 80 and got["low"][1] < got["low"][2]
