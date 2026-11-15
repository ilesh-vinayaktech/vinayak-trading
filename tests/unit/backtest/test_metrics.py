import math
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from algo.backtest.metrics import metrics


def curve(*vals, start=date(2025, 1, 1)):
    return [(start + timedelta(days=i), D(v)) for i, v in enumerate(vals)]


def test_too_short_curve_has_no_metrics():
    assert metrics([])["total_return"] is None and metrics(curve(100))["sharpe"] is None


def test_hand_computed_values():
    m = metrics(curve(100, 110, 99))  # +10%, -10%
    assert m["total_return"] == pytest.approx(-0.01)
    assert m["max_drawdown"] == pytest.approx(-0.10)
    mean, sd = 0.0, math.sqrt((0.1**2 + 0.1**2) / 1)
    assert m["vol"] == pytest.approx(sd * math.sqrt(252))
    assert m["sharpe"] == pytest.approx(mean / sd * math.sqrt(252) if sd else 0)


def test_cagr_uses_calendar_years():
    m = metrics(curve(100, 121, start=date(2024, 1, 1)) + [(date(2026, 1, 1), D(144))])
    assert m["cagr"] == pytest.approx(1.44 ** (1 / (731 / 365.25)) - 1)


def test_flat_curve_has_zero_vol_and_no_sharpe():
    m = metrics(curve(100, 100, 100))
    assert m["vol"] == 0 and m["sharpe"] is None and m["max_drawdown"] == 0


def test_single_return_has_zero_variance_not_a_crash():
    assert metrics(curve(100, 105))["vol"] == 0


# ---- independent cross-checks (mean != 0, so mean/Sharpe errors cannot hide) ----------------
def test_values_match_an_independent_computation_with_a_non_zero_mean():
    import statistics

    c = curve(100, 102, 101, 105, 104, start=date(2025, 1, 1))
    vals = [float(v) for _, v in c]
    rets = [b / a - 1 for a, b in zip(vals, vals[1:], strict=False)]
    m = metrics(c)
    sd = statistics.stdev(rets)
    assert m["vol"] == pytest.approx(sd * math.sqrt(252))
    assert m["sharpe"] == pytest.approx(statistics.mean(rets) / sd * math.sqrt(252))
    assert m["total_return"] == pytest.approx(104 / 100 - 1)
    assert m["max_drawdown"] == pytest.approx(101 / 102 - 1)  # peak 102 -> trough 101
    years = 4 / 365.25
    assert m["cagr"] == pytest.approx(1.04 ** (1 / years) - 1)


def test_drawdown_starts_from_the_first_value_not_the_second():
    assert metrics(curve(100, 90, 95))["max_drawdown"] == pytest.approx(-0.10)


def test_sharpe_sign_follows_the_mean_return():
    assert metrics(curve(100, 101, 103, 106, 110))["sharpe"] > 0
    assert metrics(curve(100, 99, 97, 94, 90))["sharpe"] < 0


def test_result_keys_are_stable():
    keys = {"total_return", "cagr", "vol", "sharpe", "max_drawdown", "sortino", "calmar"}
    assert set(metrics(curve(100))) == keys and set(metrics(curve(100, 101, 102))) == keys


def test_cagr_is_reported_for_periods_shorter_than_a_year_but_not_for_zero_length():
    half_year = [(date(2025, 1, 1), D(100)), (date(2025, 7, 1), D(110))]
    years = 181 / 365.25
    assert metrics(half_year)["cagr"] == pytest.approx(1.1 ** (1 / years) - 1)
    same_day = [(date(2025, 1, 1), D(100)), (date(2025, 1, 1), D(110))]
    assert metrics(same_day)["cagr"] is None


def test_a_curve_starting_at_zero_has_no_metrics_instead_of_crashing():
    m = metrics([(date(2025, 1, 1), D(0)), (date(2026, 1, 1), D(110))])
    assert set(m.values()) == {None}


def test_a_wipe_out_is_reported_not_a_crash():
    """Equity hitting zero is exactly when a report is needed; later values are meaningless."""
    m = metrics(curve(100, 50, 0, 0, 0))
    assert m["total_return"] == pytest.approx(-1.0) and m["max_drawdown"] == pytest.approx(-1.0)
    assert m["vol"] is not None and m["cagr"] == pytest.approx(-1.0)


# ---- Sortino and Calmar ----------------------------------------------------------------------
def test_sortino_and_calmar_match_a_hand_computation():
    c = curve(100, 102, 99, 103, 101)  # returns +2%, -2.941176%, +4.040404%, -1.941748%
    vals = [100, 102, 99, 103, 101]
    rets = [b / a - 1 for a, b in zip(vals, vals[1:], strict=False)]
    downside = math.sqrt(
        sum(min(r, 0) ** 2 for r in rets) / len(rets)
    )  # target 0, divided by ALL periods
    m = metrics(c)
    assert m["sortino"] == pytest.approx(sum(rets) / len(rets) / downside * math.sqrt(252))
    assert m["calmar"] == pytest.approx(m["cagr"] / abs(m["max_drawdown"]))


def test_sortino_and_calmar_are_none_when_there_is_no_downside_or_no_drawdown_and_in_short_curves():
    up = metrics(curve(100, 101, 102, 104))
    assert up["sortino"] is None and up["calmar"] is None and up["max_drawdown"] == 0
    short = metrics(curve(100))
    assert short["sortino"] is None and short["calmar"] is None


# ---- the branches the first tests never reached (found by mutation testing) -----------------------
def test_a_curve_that_starts_at_or_below_zero_has_no_metrics_at_all_with_every_key_present():
    for first in (0, -5):
        m = metrics(curve(first, 100, 110))
        assert m == {
            "total_return": None, "cagr": None, "vol": None, "sharpe": None,
            "max_drawdown": None, "sortino": None, "calmar": None,
        }, first  # fmt: skip


def test_a_curve_that_starts_at_exactly_one_is_measured_like_any_other():
    m = metrics(curve(1, 2, 3))
    assert (
        m["total_return"] == pytest.approx(2.0) and m["cagr"] is not None and m["max_drawdown"] == 0
    )


def test_a_wipe_out_ends_the_curve_there_and_a_balance_of_one_is_not_a_wipe_out():
    m = metrics(curve(100, 50, 0, 10, 20))  # after the zero nothing counts
    assert m["total_return"] == pytest.approx(-1.0) and m["max_drawdown"] == pytest.approx(-1.0)
    assert m["vol"] == pytest.approx(
        metrics(curve(100, 50, 0))["vol"]
    )  # the later days change nothing
    kept = metrics(curve(100, 1, 2))
    assert kept["total_return"] == pytest.approx(2 / 100 - 1) and kept[
        "max_drawdown"
    ] == pytest.approx(1 / 100 - 1)
    ruined_at_once = metrics(curve(100, 0))
    assert ruined_at_once["cagr"] == pytest.approx(
        -1.0
    )  # the second value is zero: still a rate of return, not a missing one
