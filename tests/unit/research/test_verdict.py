import math
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from algo.backtest.report import round_trips
from algo.backtest.validation import registry
from algo.research.verdict import (
    EMBARGO,
    TEST,
    TRAIN,
    VerdictError,
    analyse,
    contributions,
    inputs,
    neighbours,
)

N = TRAIN + EMBARGO + TEST + 2 * TEST - TEST + 40  # two walk-forward windows
GRID = {"a": [1, 2, 3]}
COMBOS = [{"a": v} for v in GRID["a"]]
START = date(2020, 12, 1)  # the series crosses into 2021 so there is more than one regime year


def days(n=N):
    return [START + timedelta(days=i) for i in range(n + 1)]


def series(drift, n=N):
    return [drift + 0.01 * math.sin(i / 3) for i in range(n)]


def stored(drifts=(0.0005, 0.001, 0.002), n=N):
    return {registry.params_hash(c): series(d, n) for c, d in zip(COMBOS, drifts, strict=True)}


def test_neighbours_are_one_step_away_in_the_grid_one_setting_at_a_time():
    assert neighbours({"a": 2, "b": 10}, {"a": [1, 2, 3], "b": [10, 20]}) == [
        {"a": 1, "b": 10},
        {"a": 3, "b": 10},
        {"a": 2, "b": 20},
    ]
    assert neighbours({"a": 1}, GRID) == [{"a": 2}]  # an edge has one neighbour


def test_walk_forward_judges_only_days_the_choice_never_saw():
    a = analyse(days(), COMBOS, stored(), GRID)
    assert len(a.windows) == 2 and len(a.oos_returns) == 2 * TEST
    first = a.windows[0]
    assert first["chosen"] == {"a": 3}  # best Sharpe on the training days
    assert first["train_to"] < first["test_from"]  # train ends before test starts
    gap = date.fromisoformat(first["test_from"]) - date.fromisoformat(first["train_to"])
    assert gap.days == EMBARGO + 1  # the embargo sits between them
    assert (
        a.oos_returns[:TEST]
        == stored()[registry.params_hash({"a": 3})][TRAIN + EMBARGO : TRAIN + EMBARGO + TEST]
    )


def test_the_best_overall_setting_is_compared_with_its_neighbours():
    a = analyse(days(), COMBOS, stored(), GRID)
    assert a.base == {"a": 3} and len(a.neighbour_sharpes) == 1
    assert a.base_sharpe is not None and a.neighbour_sharpes[0] is not None
    assert a.neighbour_sharpes[0] < a.base_sharpe  # the neighbour (a=2) is worse


def test_regimes_and_benchmark_follow_the_out_of_sample_days():
    bench = [0.0001 * i for i in range(N)]
    a = analyse(days(), COMBOS, stored(), GRID, bench)
    assert len(a.benchmark_oos) == len(a.oos_returns) == len(a.regime_labels)
    assert a.benchmark_oos[0] == bench[TRAIN + EMBARGO]  # same index as the first test day
    assert set(a.regime_labels) >= {"2022"}  # calendar years of the OOS days
    assert analyse(days(), COMBOS, stored(), GRID).benchmark_oos == []


def test_window_returns_compound_each_windows_days():
    a = analyse(days(), COMBOS, stored(), GRID)
    r = stored()[registry.params_hash({"a": 3})][TRAIN + EMBARGO : TRAIN + EMBARGO + TEST]
    expect = math.prod(1 + x for x in r) - 1
    assert a.window_returns[0] == pytest.approx(expect)
    assert a.windows[0]["return"] == pytest.approx(expect)


def test_missing_short_or_misaligned_inputs_are_refused_with_the_reason():
    with pytest.raises(VerdictError, match="run all trials"):
        analyse(days(), COMBOS, dict(list(stored().items())[:2]), GRID)
    with pytest.raises(VerdictError, match="too short"):
        analyse(days(100), COMBOS, stored(n=100), GRID)
    with pytest.raises(VerdictError, match="different days"):
        analyse(days(), COMBOS, {**stored(), registry.params_hash(COMBOS[0]): [0.0] * 5}, GRID)
    with pytest.raises(VerdictError, match="benchmark"):
        analyse(days(), COMBOS, stored(), GRID, [0.0] * 5)


def test_an_edge_best_with_a_single_value_grid_has_no_neighbours_to_compare():
    one = {"a": [1]}
    s = {registry.params_hash({"a": 1}): series(0.001)}
    a = analyse(days(), [{"a": 1}], s, one)
    assert a.neighbour_sharpes == []  # the plateau gate will then fail for missing evidence


def test_contributions_and_inputs_feed_the_concentration_gates():
    fills = [
        (1, date(2024, 1, 1), 7, "BUY", D(10), D(100), D(0)),
        (2, date(2024, 1, 9), 7, "SELL", D(10), D(110), D(0)),  # +100
        (3, date(2024, 2, 1), 8, "BUY", D(10), D(100), D(0)),
        (4, date(2024, 2, 9), 8, "SELL", D(10), D(90), D(0)),  # -100
    ]
    trips = round_trips(fills)
    stock, month, trade = contributions(trips)
    assert stock == {"7": 100.0, "8": -100.0}
    assert month == {"2024-01": 100.0, "2024-02": -100.0}
    assert trade == {"0": 100.0, "1": -100.0}
    a = analyse(days(), COMBOS, stored(), GRID)
    i = inputs(
        a, n_trials=3, trial_sharpes=[0.1, 0.2, 0.3], trial_returns=list(stored().values()),
        plateau_tolerance=0.3, returns_2x_costs=series(0.0005), returns_3x_capital=series(0.001), trips=trips,
    )  # fmt: skip
    assert i.n_trials == 3 and i.by_instrument == stock and i.base_sharpe == a.base_sharpe


# ---- the holdout: the final, one-time test of the chosen settings -------------------------------------------

from algo.backtest.validation.gates import Thresholds  # noqa: E402
from algo.research.verdict import holdout_gates  # noqa: E402

TH = Thresholds(0.8, 0.95, 0.2, 1.25, 0.25, 0.3, 0.5, 0.2, 252, 2, 0.5, 0.02)


def calm(drift, n=120):
    return [drift + 0.004 * math.sin(i) for i in range(n)]


def by_name(gates):
    return {g["name"]: g for g in gates}


def test_a_strong_calm_holdout_that_beats_the_index_passes_every_gate():
    g = by_name(holdout_gates(calm(0.003), calm(0.0005), TH)[0])
    assert {k: v["passed"] for k, v in g.items()} == {
        "holdout_sharpe": True, "holdout_drawdown": True, "holdout_beats_benchmark": True,
    }  # fmt: skip


def test_each_gate_fails_for_its_own_reason_and_says_it():
    weak, ev = holdout_gates(calm(0.0001), calm(0.0005), TH)
    g = by_name(weak)
    assert not g["holdout_sharpe"]["passed"] and "required 0.8" in g["holdout_sharpe"]["detail"]
    assert not g["holdout_beats_benchmark"]["passed"]
    deep = [0.01] * 20 + [-0.05] * 8 + [0.01] * 20
    assert not by_name(holdout_gates(deep, calm(0.0005, 48), TH)[0])["holdout_drawdown"]["passed"]
    assert ev["days"] == 120 and ev["sharpe"] is not None


def test_without_a_benchmark_that_gate_fails_for_missing_evidence_and_the_rest_still_run():
    g = by_name(holdout_gates(calm(0.003), None, TH)[0])
    assert g["holdout_beats_benchmark"] == {
        "name": "holdout_beats_benchmark",
        "passed": False,
        "detail": "evidence missing",
    }
    assert g["holdout_sharpe"]["passed"] and g["holdout_drawdown"]["passed"]


def test_an_undefined_sharpe_fails_instead_of_passing():
    g = by_name(
        holdout_gates([0.001] * 10, calm(0.0005, 10), TH)[0]
    )  # zero variance: Sharpe undefined
    assert g["holdout_sharpe"] == {
        "name": "holdout_sharpe",
        "passed": False,
        "detail": "evidence missing",
    }
