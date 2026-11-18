# ruff: noqa: E501
"""The forecast model: it learns a real signal, never sees the outcome of the day it predicts (walk-forward), says so when there is nothing to learn, and is
scored against the plain base rate."""

import numpy as np
import pytest

from algo.market import predict

NAMES = ("signal", "noise")


def world(n=1500, edge=1.5, seed=3):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, 2))
    y = (rng.random(n) < 1 / (1 + np.exp(-edge * x[:, 0]))).astype(
        float
    )  # only the first column carries information
    return x, y, np.arange(n)


def test_a_real_signal_is_learned_and_beats_the_base_rate_out_of_sample():
    x, y, day = world()
    p, mask = predict.walk_forward(x, y, day, 1, NAMES)
    assert mask.sum() == len(x) - predict.MIN_TRAIN
    s = predict.skill(p[mask], y[mask])
    assert s.brier_skill > 0.05 and s.hit_rate > s.base_hit + 0.05


def test_pure_noise_does_not_beat_the_base_rate_and_is_reported_as_such():
    x, y, day = world(edge=0.0)
    p, mask = predict.walk_forward(x, y, day, 1, NAMES)
    s = predict.skill(p[mask], y[mask])
    assert s.brier_skill < 0.02  # nothing to learn: no skill claimed


def test_a_prediction_never_depends_on_outcomes_that_were_not_yet_known():
    x, y, day = world()
    horizon = 5
    p, _ = predict.walk_forward(x, y, day, horizon, NAMES)
    cut = 900
    y2 = y.copy()
    y2[cut:] = 1 - y2[cut:]  # rewrite every outcome from `cut` on
    p2, _ = predict.walk_forward(x, y2, day, horizon, NAMES)
    ok = ~np.isnan(p)
    # a prediction for day t used only outcomes up to t - horizon, so days up to cut + horizon are untouched (the model refits only every REFIT days)
    assert np.allclose(p[ok & (day < cut + horizon)], p2[ok & (day < cut + horizon)])
    assert not np.allclose(
        p[ok & (day > cut + 3 * predict.REFIT)], p2[ok & (day > cut + 3 * predict.REFIT)]
    )


def test_pooled_rows_share_a_day_and_unknown_outcomes_are_left_out_of_training():
    x, y, day = world(n=600)
    xs, ys, ds = np.vstack([x, x]), np.concatenate([y, y]), np.concatenate([day, day])
    order = np.argsort(ds, kind="stable")
    ys[-20:] = np.nan  # outcomes not known yet
    p, mask = predict.walk_forward(xs[order], ys[order], ds[order], 1, NAMES)
    assert mask.any() and not np.isnan(p[mask]).any()


def test_a_single_outcome_has_nothing_to_learn_and_an_empty_set_has_no_skill():
    assert predict.fit(np.zeros((10, 2)), np.ones(10), NAMES) is None
    assert predict.fit(np.zeros((0, 2)), np.zeros(0), NAMES) is None
    assert predict.skill(np.array([]), np.array([])) is None


def test_the_evidence_names_the_features_that_moved_the_probability_most():
    x, y, _ = world()
    m = predict.fit(x, y, NAMES)
    ev = m.evidence(np.array([2.0, 0.0]))
    assert ev[0]["feature"] == "signal" and ev[0]["effect"] > 0
    assert m.p_up(np.array([2.0, 0.0]))[0] > 0.7 > 0.3 > m.p_up(np.array([-2.0, 0.0]))[0]


def test_skill_calibration_bins_cover_every_prediction():
    p = np.linspace(0.1, 0.9, 200)
    up = (np.random.default_rng(1).random(200) < p).astype(float)
    s = predict.skill(p, up)
    assert sum(n for _, _, n in s.calibration) == 200 and s.calibration[0][0] < s.calibration[-1][0]
    assert s.brier_skill > 0 and s.base_hit >= 0.5 and pytest.approx(s.base_rate) == up.mean()


def test_a_missing_figure_is_filled_from_the_training_period_and_pushes_nothing():
    rng = np.random.default_rng(3)
    x = rng.normal(size=(400, 2))
    y = (x[:, 0] + rng.normal(0, 0.5, 400) > 0).astype(float)
    x_missing = x.copy()
    x_missing[::5, 1] = np.nan  # a fifth of one column is missing in training
    model = predict.fit(x_missing, y, ("a", "b"))
    row = np.array([1.0, np.nan])
    assert not np.isnan(model.p_up(row)).any()
    assert model.p_up(row)[0] == pytest.approx(
        model.p_up(np.array([1.0, model.mean[1]]))[0]
    )  # missing counts as the training average
    assert [e["feature"] for e in model.evidence(row)] == ["a"]  # and is never named as a reason
