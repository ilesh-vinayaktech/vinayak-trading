from datetime import date

import pytest

from algo.backtest.validation.robustness import by_year, concentration, perturbations, plateau


def test_perturbations_vary_one_numeric_parameter_at_a_time():
    out = perturbations({"lookback": 100, "thr": 0.5, "name": "x", "flag": True})
    assert {"lookback": 80, "thr": 0.5, "name": "x", "flag": True} in out
    assert {"lookback": 120, "thr": 0.5, "name": "x", "flag": True} in out
    assert any(o["thr"] == pytest.approx(0.4) for o in out) and len(out) == 4
    assert all(o["name"] == "x" and o["flag"] is True for o in out)  # non-numerics untouched


def test_integer_parameters_stay_integers_and_unchanged_values_are_dropped():
    out = perturbations({"n": 10})
    assert [o["n"] for o in out] == [8, 12] and all(isinstance(o["n"], int) for o in out)
    assert perturbations({"n": 1}) == []  # 0.8 and 1.2 both round to 1: no change, no duplicate


def test_plateau_is_stable_when_neighbours_keep_enough_of_the_sharpe():
    p = plateau(1.0, [0.9, 1.1, 0.75])
    assert p.stable and p.worst == 0.75 and p.worst_drop == pytest.approx(0.25)
    assert not plateau(1.0, [0.9, 0.6]).stable
    assert plateau(1.0, [0.7]).stable  # exactly at the 30% tolerance
    assert plateau(1.0, [2.0]).worst_drop == 0.0  # improvement is not a drop
    assert plateau(1.0, []).stable  # nothing to compare with => base only


def test_an_undefined_neighbour_counts_as_a_collapse_and_a_losing_base_is_never_stable():
    assert not plateau(1.0, [0.9, None]).stable
    assert plateau(1.0, [0.9, None]).worst_drop == 1.0
    lost = plateau(-0.2, [-0.1, None, 0.3])
    assert not lost.stable and lost.worst == -0.1 and lost.worst_drop == 1.0
    assert plateau(0.0, [None]).worst == 0.0


def test_by_year_compounds_returns_and_counts_days():
    days = [date(2022, 12, 30), date(2023, 1, 2), date(2023, 1, 3)]
    out = by_year(days, [0.1, 0.1, -0.1])
    assert out[2022]["return"] == pytest.approx(0.1) and out[2022]["sharpe"] is None
    assert out[2023]["return"] == pytest.approx(1.1 * 0.9 - 1) and out[2023]["days"] == 2
    assert list(out) == [2022, 2023]
    with pytest.raises(ValueError, match="differ in length"):
        by_year(days, [0.1])


def test_concentration_is_the_top_share_of_positive_contribution():
    c = {"A": 60.0, "B": 20.0, "C": 10.0, "D": 10.0, "E": -50.0}
    assert concentration(c, top=1) == pytest.approx(0.6)
    assert concentration(c, top=3) == pytest.approx(0.9)
    assert concentration({"A": -1.0}) == 0.0 and concentration({}) == 0.0
