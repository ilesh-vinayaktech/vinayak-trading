import math
import random

import pytest

from algo.factory import dsl, experiment

BASE = dsl.StrategyDef.model_validate(
    {
        "strategy_id": "MOM_001", "version": 1, "description": "momentum", "universe": "MEMBERS", "timeframe": "DAILY",
        "entry": {"all": [{"feature": "ret_60d", "op": ">", "value": 0.05}, {"feature": "dist_sma_50d", "op": ">", "value": 0}]},
        "exit": {"any": [{"feature": "dist_sma_50d", "op": "<", "value": 0}]},
        "ranking": {"feature": "ret_60d", "order": "DESC"},
        "position": {"max_positions": 10, "sizing": "EQUAL_WEIGHT"}, "risk": {"max_position_percent": 10},
        "rebalance": "WEEKLY",
    }
)  # fmt: skip


def test_a_grid_expands_to_every_combination_in_a_stable_order_and_each_variant_is_a_valid_definition():
    grid = {"position.max_positions": [5, 10], "entry.all.0.value": [0.02, 0.05, 0.08]}
    out, skipped = experiment.variants(BASE, grid)
    assert skipped == [] and len(out) == 6
    # keys are taken in sorted order (entry... before position...), values in the order given, last key varying fastest
    assert [v.overrides for v in out][:3] == [
        {"entry.all.0.value": 0.02, "position.max_positions": 5},
        {"entry.all.0.value": 0.02, "position.max_positions": 10},
        {"entry.all.0.value": 0.05, "position.max_positions": 5},
    ]
    assert out[0].defn.position.max_positions == 5 and str(out[0].defn.entry.all[0].value) == "0.02"
    assert len({v.defn.sha256 for v in out}) == 6  # every combination is a different strategy
    assert all(
        v.defn.strategy_id == "MOM_001" and v.defn.version == 1 for v in out
    )  # an experiment is not a new registered version
    assert experiment.variants(BASE, grid)[0][0].overrides == out[0].overrides  # and repeatable


def test_the_base_definition_is_never_changed_by_building_variants():
    before = BASE.sha256
    experiment.variants(BASE, {"risk.max_position_percent": [5, 15]})
    assert BASE.sha256 == before


def test_a_combination_that_makes_an_invalid_definition_is_skipped_with_its_reason_and_still_counts_as_a_trial():
    out, skipped = experiment.variants(BASE, {"position.max_positions": [0, 5, 99]})
    assert [v.overrides["position.max_positions"] for v in out] == [5]
    assert [s.overrides["position.max_positions"] for s in skipped] == [0, 99]
    assert "max_positions" in skipped[0].reason and experiment.trial_count(out, skipped) == 3


def test_paths_must_name_an_existing_leaf_and_the_identity_of_the_strategy_cannot_be_overridden():
    for bad in (
        "entry.all.5.value",
        "nosuch",
        "entry.all.0.nope",
        "entry.all",
        "position",
        "entry.all.0",
        "entry.all.9",
        "entry.all.x",
        "nosuch.deeper",
        "entry.all.0.value.deeper",
    ):
        with pytest.raises(experiment.ExperimentError, match="not a field you can vary|no such"):
            experiment.variants(BASE, {bad: [1]})
    for identity in ("version", "strategy_id", "description"):
        with pytest.raises(experiment.ExperimentError, match="identity"):
            experiment.variants(BASE, {identity: ["X"]})


def test_an_empty_grid_a_grid_with_an_empty_axis_and_too_many_combinations_are_refused_never_truncated():
    for bad in ({}, {"position.max_positions": []}):
        with pytest.raises(experiment.ExperimentError, match="nothing to vary"):
            experiment.variants(BASE, bad)
    with pytest.raises(experiment.ExperimentError, match="more than 6 combinations"):
        experiment.variants(
            BASE,
            {"position.max_positions": [1, 2, 3], "risk.max_position_percent": [5, 6, 7]},
            max_trials=6,
        )
    out, _ = experiment.variants(
        BASE,
        {"position.max_positions": [1, 2, 3], "risk.max_position_percent": [5, 6]},
        max_trials=6,
    )
    assert len(out) == 6  # exactly the limit is allowed


def trial(overrides, returns):
    return experiment.TrialResult(overrides, "h" * 64, {}, "r" * 64, returns)


def noisy(seed, drift, n=250, vol=0.01):
    rng = random.Random(seed)
    return [rng.gauss(drift, vol) for _ in range(n)]


def test_the_comparison_ranks_by_sharpe_and_reports_how_good_the_best_would_have_to_be_to_beat_luck():
    # drifts per day: nothing, a little, a lot (a 0.5% daily drift on 1% volatility), a little negative
    trials = [trial({"k": i}, noisy(i, d)) for i, d in enumerate([0.0, 0.0005, 0.005, -0.0005])]
    c = experiment.compare(trials)
    assert (
        c.n_trials == 4 and [t.overrides["k"] for t in c.ranked][0] == 2
    )  # the strongest drift ranks first
    sharpes = [t.sharpe for t in c.ranked]
    assert sharpes == sorted(sharpes, reverse=True)
    assert c.expected_max_sharpe > 0 and c.sr_variance > 0
    assert (
        c.best.deflated_sharpe is not None and c.best.deflated_sharpe > 0.99
    )  # far above what four tries of luck give
    # a moderate edge is only about a coin flip once the spread among the tries is counted as the luck benchmark (the correction is deliberately conservative)
    moderate = experiment.compare(
        [trial({"k": i}, noisy(i, d)) for i, d in enumerate([0.0, 0.0005, 0.002, -0.0005])]
    )
    assert 0.3 < moderate.best.deflated_sharpe < 0.8


def test_more_trials_make_the_same_best_result_less_convincing():
    best = noisy(1, 0.0008)
    few = experiment.compare([trial({"k": 0}, best), trial({"k": 1}, noisy(2, 0.0))])
    many = experiment.compare(
        [trial({"k": 0}, best), *[trial({"k": i}, noisy(10 + i, 0.0)) for i in range(1, 60)]]
    )
    assert few.best.overrides == many.best.overrides == {"k": 0}
    assert (
        many.expected_max_sharpe > few.expected_max_sharpe
        and many.best.deflated_sharpe < few.best.deflated_sharpe
    )


def test_pure_noise_is_not_promoted_by_trying_many_things():
    c = experiment.compare([trial({"k": i}, noisy(100 + i, 0.0)) for i in range(40)])
    assert (
        c.best.deflated_sharpe is not None and c.best.deflated_sharpe < 0.95
    )  # the winner of 40 coin flips is not evidence


def test_trials_without_a_defined_sharpe_rank_last_and_a_single_trial_has_no_spread():
    flat = trial({"k": "flat"}, [0.0] * 50)  # no variation: the Sharpe is undefined
    c = experiment.compare([flat, trial({"k": 1}, noisy(3, 0.001))])
    assert c.ranked[0].overrides == {"k": 1} and c.ranked[-1].sharpe is None
    one = experiment.compare([trial({"k": 1}, noisy(3, 0.001))])
    assert one.n_trials == 1 and one.sr_variance == 0 and one.expected_max_sharpe == 0
    assert experiment.compare([flat]).best.deflated_sharpe is None
    with pytest.raises(experiment.ExperimentError, match="no trials"):
        experiment.compare([])


def test_the_annualised_sharpe_is_reported_alongside_the_per_period_one():
    t = trial({"k": 1}, noisy(4, 0.001))
    c = experiment.compare([t])
    assert c.best.annualised_sharpe == pytest.approx(c.best.sharpe * math.sqrt(252))


def test_skipped_and_failed_attempts_count_as_tries_so_the_bar_for_the_winner_rises():
    trials = [trial({"k": i}, noisy(i, d)) for i, d in enumerate([0.0, 0.0005, 0.002])]
    finished = experiment.compare(trials)
    tried_more = experiment.compare(
        trials, attempts=30
    )  # 27 more combinations were tried and did not finish
    assert finished.n_trials == 3 and tried_more.n_trials == 30
    assert (
        tried_more.expected_max_sharpe > finished.expected_max_sharpe
        and tried_more.best.deflated_sharpe < finished.best.deflated_sharpe
    )
    with pytest.raises(experiment.ExperimentError, match="attempts cannot be fewer"):
        experiment.compare(trials, attempts=2)


# ---- found by mutation testing ---------------------------------------------------------------------------------------
def test_every_refusal_has_its_exact_words():
    def why(grid, **kw):
        with pytest.raises(experiment.ExperimentError) as e:
            experiment.variants(BASE, grid, **kw)
        return str(e.value)

    assert why({}) == "nothing to vary: give at least one path with at least one value"
    assert (
        why({"entry.all.2.value": [1]}) == "no such field 'entry.all.2.value'"
    )  # two conditions: index 2 is one past the end
    assert why({"entry.all.2": [1]}) == "no such field 'entry.all.2'"
    assert (
        why({"entry.all.0": [1]})
        == "'entry.all.0' is not a field you can vary: it is a whole group, name one value inside it"
    )
    assert (
        why({"position": [1]})
        == "'position' is not a field you can vary: it is a whole group, name one value inside it"
    )
    assert why({"entry.all.0.nope": [1]}) == "no such field 'entry.all.0.nope'"
    assert why({"nosuch.deeper": [1]}) == "no such field 'nosuch.deeper'"
    assert (
        why({"version": [2]})
        == "'version' is part of the strategy's identity and cannot be varied: an experiment is not a new version"
    )
    assert (
        why({"position.max_positions": [1, 2], "risk.max_position_percent": [5, 6]}, max_trials=3)
        == "the grid makes 4 trials: more than 3 combinations are not run (narrow the grid)"
    )


def test_the_default_limit_is_sixty_four_trials():
    out, skipped = experiment.variants(
        BASE, {"position.max_positions": list(range(1, 65))}
    )  # 64 values: allowed (some are invalid and skipped)
    assert experiment.trial_count(out, skipped) == 64
    with pytest.raises(experiment.ExperimentError, match="65 trials: more than 64 combinations"):
        experiment.variants(BASE, {"position.max_positions": list(range(1, 66))})


def test_variants_and_skipped_keep_their_place_in_the_grid_and_say_why_in_field_terms():
    out, skipped = experiment.variants(BASE, {"position.max_positions": [0, 3, 99, 5]})
    assert [v.index for v in out] == [1, 3] and [s.index for s in skipped] == [0, 2]
    assert skipped[0].reason == "position.max_positions: Input should be greater than or equal to 1"


def test_the_ranked_rows_carry_each_trials_hashes_and_metrics_through():
    t = experiment.TrialResult({"k": 1}, "a" * 64, {"trades": 7}, "b" * 64, noisy(1, 0.001))
    row = experiment.compare([t]).best
    assert (row.overrides, row.definition_sha256, row.metrics, row.result_hash) == (
        {"k": 1},
        "a" * 64,
        {"trades": 7},
        "b" * 64,
    )


def test_the_spread_of_the_trials_sharpes_is_their_sample_variance_exactly():
    import statistics

    two = experiment.compare(
        [
            trial({"k": 1}, noisy(1, 0.002)),
            trial({"k": 2}, noisy(2, 0.0)),
        ]
    )
    three = experiment.compare(
        [trial({"k": i}, noisy(i, d)) for i, d in enumerate([0.002, 0.0, 0.001])]
    )
    for c in (two, three):
        assert c.sr_variance == pytest.approx(
            statistics.variance([r.sharpe for r in c.ranked]), rel=1e-12
        )


def test_refusals_of_the_comparison_have_their_exact_words():
    with pytest.raises(experiment.ExperimentError) as e:
        experiment.compare([])
    assert str(e.value) == "no trials to compare"
    with pytest.raises(experiment.ExperimentError) as e2:
        experiment.compare([trial({"k": 1}, noisy(1, 0.001))], attempts=0)
    assert str(e2.value) == "attempts cannot be fewer than the trials that finished"
    assert (
        experiment.compare([trial({"k": 1}, noisy(1, 0.001))], attempts=1).n_trials == 1
    )  # as many attempts as trials is fine


def test_building_variants_never_leaks_an_edit_from_one_combination_into_the_next():
    out, _ = experiment.variants(BASE, {"entry.all.0.value": [0.02, 0.09]})
    assert [str(v.defn.entry.all[0].value) for v in out] == ["0.02", "0.09"] and str(
        BASE.entry.all[0].value
    ) == "0.05"


def test_a_combination_with_two_invalid_values_gives_both_reasons_in_one_line():
    _, skipped = experiment.variants(
        BASE, {"position.max_positions": [0], "risk.max_position_percent": [0]}
    )
    assert (
        skipped[0].reason
        == "position.max_positions: Input should be greater than or equal to 1; risk.max_position_percent: Input should be greater than 0"
    )
