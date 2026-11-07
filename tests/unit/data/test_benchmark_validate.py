from datetime import date
from decimal import Decimal as D

import pytest

from algo.data.benchmark_validate import (
    ReturnCheck,
    WindowResponse,
    compare_sessions,
    reconcile_returns,
    validate_series,
)  # fmt: skip
from algo.data.providers.niftyindices_tri import Observation

B = date(2004, 1, 1)


def ob(d, v):
    return Observation(d, D(str(v)), None)


def win(s, e, *obs):
    return WindowResponse(s, e, tuple(obs))


def check(v, name):
    return next(c for c in v.checks if c.name == name)


def test_a_clean_series_passes_and_keeps_its_levels_and_largest_moves():
    r = [
        win(
            B,
            date(2004, 12, 30),
            ob(B, "1000.00"),
            ob(date(2004, 1, 2), "1010.00"),
            ob(date(2004, 1, 5), "1000.00"),
        )
    ]
    v = validate_series(r, base_date=B, base_level=D("1000.00"))
    assert v.passed and v.failures() == [] and len(v.levels) == 3 and v.gaps == []
    assert v.largest_moves[0][1] == date(2004, 1, 2)
    assert float(v.largest_moves[0][0]) == pytest.approx(0.01)


def test_wrong_first_date_or_base_level_fails_with_the_values_named():
    v = validate_series(
        [win(B, B, ob(date(2004, 1, 2), "999.00"))], base_date=B, base_level=D("1000.00")
    )
    assert (
        not check(v, "first_observation").passed
        and "2004-01-02" in check(v, "first_observation").detail
    )
    assert not check(v, "base_level").passed and "999.00" in check(v, "base_level").detail


def test_duplicates_are_reported_and_conflicting_values_are_never_resolved():
    a = win(B, date(2004, 6, 30), ob(B, "1000.00"), ob(date(2004, 1, 2), "1010.00"))
    b = win(
        date(2004, 1, 2),
        date(2004, 12, 31),
        ob(date(2004, 1, 2), "1010.00"),
        ob(date(2004, 1, 5), "1020.00"),
    )
    same = validate_series([a, b], base_date=B, base_level=D("1000.00"))
    assert not check(same, "duplicate_dates").passed and check(same, "conflicting_values").passed
    assert same.levels[date(2004, 1, 2)] == D("1010.00")  # identical overlap is consistent
    c = win(date(2004, 1, 2), date(2004, 12, 31), ob(date(2004, 1, 2), "1011.00"))
    conflict = validate_series([a, c], base_date=B, base_level=D("1000.00"))
    assert (
        not check(conflict, "conflicting_values").passed
        and "2004-01-02" in check(conflict, "conflicting_values").detail
    )
    assert (
        conflict.levels == {} and conflict.largest_moves == []
    )  # no series is produced from a conflict


def test_rows_outside_their_window_and_non_positive_levels_fail():
    v = validate_series([win(B, date(2004, 1, 3), ob(B, "1000.00"), ob(date(2004, 2, 1), "0.00"))],
                        base_date=B, base_level=D("1000.00"))  # fmt: skip
    assert not check(v, "inside_requested_window").passed and not check(v, "positive_levels").passed


def test_gaps_over_the_threshold_are_listed_not_filled():
    v = validate_series([win(B, date(2004, 3, 1), ob(B, "1000.00"), ob(date(2004, 1, 20), "1001.00"))],
                        base_date=B, base_level=D("1000.00"))  # fmt: skip
    assert v.gaps == [(B, date(2004, 1, 20))] and len(v.levels) == 2
    assert validate_series([win(B, B, ob(B, "1000.00"), ob(date(2004, 1, 6), "1001.00"))], base_date=B,
                           base_level=D("1000.00"), gap_days=5).gaps == []  # exactly 5 days is allowed  # fmt: skip


def test_an_empty_response_is_a_failure():
    v = validate_series([win(B, B)], base_date=B, base_level=D("1000.00"))
    assert not v.passed and check(v, "not_empty").detail == "no observations"


def test_dates_are_compared_with_a_calendar_in_both_directions():
    extra, missing = compare_sessions(
        [date(2026, 2, 1), date(2026, 2, 2)], [date(2026, 2, 2), date(2026, 2, 3)]
    )
    assert extra == [date(2026, 2, 1)] and missing == [date(2026, 2, 3)]


def test_published_returns_are_recomputed_with_a_stated_convention_and_tolerance():
    lv = {date(2020, 1, 1): D("100"), date(2021, 1, 1): D("110"), date(2025, 1, 1): D("161.051")}
    cum = ReturnCheck(
        "1y", date(2020, 1, 1), date(2021, 1, 1), "cumulative", D("10.00"), D("0.005")
    )
    cagr = ReturnCheck("5y", date(2020, 1, 1), date(2025, 1, 1), "cagr", D("10.00"), D("0.02"))
    off = ReturnCheck(
        "bad", date(2020, 1, 1), date(2021, 1, 1), "cumulative", D("11.00"), D("0.005")
    )
    r = reconcile_returns(lv, [cum, cagr, off])
    assert [x.passed for x in r] == [True, True, False]
    assert float(r[0].computed_pct) == pytest.approx(10.0) and float(
        r[2].difference_pp
    ) == pytest.approx(-1.0)
    with pytest.raises(KeyError, match="no level for 2022-01-01"):
        reconcile_returns(
            lv, [ReturnCheck("x", date(2020, 1, 1), date(2022, 1, 1), "cumulative", D(1), D(1))]
        )
    with pytest.raises(ValueError, match="unknown return kind"):
        reconcile_returns(
            lv, [ReturnCheck("x", date(2020, 1, 1), date(2021, 1, 1), "weird", D(1), D(1))]
        )
