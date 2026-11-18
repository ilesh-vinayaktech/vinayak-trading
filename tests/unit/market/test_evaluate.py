import numpy as np
import pytest

from algo.market import evaluate as ev

Y = np.array([1.0, 1.0, 0.0, 0.0, 1.0, 0.0])


def test_perfect_forecasts_score_perfectly_and_a_coin_flip_scores_nothing():
    m = ev.metrics(np.where(Y == 1, 0.9, 0.1), Y)
    assert (m.accuracy, m.auc, m.precision, m.recall, (m.tp, m.fp, m.fn, m.tn)) == (
        1.0,
        1.0,
        1.0,
        1.0,
        (3, 0, 0, 3),
    )
    assert ev.brier_skill(np.full(6, 0.5), Y, np.full(6, 0.5)) == 0.0
    assert ev.auc(np.full(6, 0.5), Y) == 0.5  # no ranking at all


def test_log_loss_and_brier_punish_a_confident_wrong_call_more_than_a_hedge():
    wrong = ev.metrics(np.where(Y == 1, 0.1, 0.9), Y)
    hedge = ev.metrics(np.full(6, 0.5), Y)
    assert wrong.brier > hedge.brier and wrong.log_loss > hedge.log_loss and wrong.accuracy == 0.0


def test_auc_handles_a_single_outcome_and_ties():
    assert ev.auc(np.array([0.6, 0.7]), np.array([1.0, 1.0])) is None
    assert ev.auc(np.array([0.7, 0.7, 0.3, 0.3]), np.array([1.0, 0.0, 1.0, 0.0])) == 0.5


def test_calibration_buckets_say_what_was_said_against_what_happened():
    p = np.array([0.52, 0.53, 0.72, 0.74, 0.48])
    y = np.array([1.0, 0.0, 1.0, 1.0, 0.0])
    cal = {(c["from"], c["to"]): c for c in ev.calibration(p, y)}
    assert cal[(0.5, 0.55)]["n"] == 2 and cal[(0.5, 0.55)]["actual"] == 0.5
    assert (
        cal[(0.7, 0.75)]["actual"] == 1.0 and (0.4, 0.45) not in cal
    )  # an empty bucket is left out


def test_the_reference_uses_only_outcomes_already_known_on_the_day():
    y = np.array([1.0, 1.0, 0.0, 0.0, 0.0, 0.0])
    ref = ev.expanding_base(y, horizon=1)
    assert (
        ref[0] == 0.5 and ref[1] == 1.0 and ref[2] == 1.0 and ref[3] == pytest.approx(2 / 3)
    )  # day 3 knows days 0..2
    cond = ev.expanding_conditional(np.array([True] * 6), y, horizon=1, min_obs=2)
    assert (
        cond[2] == 1.0
    )  # the signal is the same every day, so it reads like the base once two such days are known


def test_block_bootstrap_gives_an_interval_around_the_estimate_and_wider_with_less_data():
    rng = np.random.default_rng(1)
    y = (rng.random(400) < 0.6).astype(float)
    p = np.full(400, 0.6)
    stat = lambda idx: float(np.mean((p[idx] > 0.5) == (y[idx] == 1)))  # noqa: E731
    lo, hi = ev.block_ci(stat, 400, block=10, reps=300)
    assert lo < stat(np.arange(400)) < hi and hi - lo < 0.2
    lo2, hi2 = ev.block_ci(lambda idx: float(np.mean(y[:40][idx % 40])), 40, block=10, reps=300)
    assert hi2 - lo2 > hi - lo


def test_segments_with_too_few_days_are_left_out():
    p, y = np.full(60, 0.6), (np.arange(60) % 2).astype(float)
    got = ev.by_segment(["bull"] * 50 + ["bear"] * 10, p, y, np.full(60, 0.5))
    assert set(got) == {"bull"} and got["bull"]["n"] == 50


def test_the_promotion_test_shows_nothing_before_the_minimum_and_needs_the_lower_bound_above_zero():
    rng = np.random.default_rng(5)
    y = (rng.random(600) < 0.55).astype(float)
    prod = np.full(600, 0.55)
    better = np.clip(
        0.55 + 0.25 * (y - 0.55), 0.01, 0.99
    )  # a candidate that really does know something
    assert ev.primary_test(prod[:499], better[:499], y[:499]) == {
        "pairs": 499,
        "evaluated": False,
    }  # no estimate, no interval
    got = ev.primary_test(prod, better, y, reps=400)
    assert got["evaluated"] and got["delta"] > 0 and got["low"] > 0 and got["promote"] is True
    same = ev.primary_test(prod, prod, y, reps=400)
    assert (
        same["delta"] == 0 and same["promote"] is False
    )  # no better than production: not promoted
    worse = ev.primary_test(better, prod, y, reps=400)
    assert worse["delta"] < 0 and worse["promote"] is False
