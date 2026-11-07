import math
from datetime import date
from decimal import Decimal as D

import pytest

from algo.data.benchmark_compare import compare, correlation, daily_returns, percentile


def s(*pairs):
    return {date(2024, 1, d): D(str(v)) for d, v in pairs}


A = s((1, 100), (2, 101), (3, 101), (4, 103.02), (5, 104), (6, 103))  # +1%, 0%, +2%
B = s((1, 200), (2, 204), (3, 206.04), (4, 208.08), (5, 209), (6, 212))  # +2%, +1%, +1%


def test_returns_come_from_the_series_own_consecutive_observations():
    r = daily_returns(s((1, 100), (3, 110)))  # day 2 missing: one 10% return over 1 -> 3
    assert r == {date(2024, 1, 3): (date(2024, 1, 1), pytest.approx(0.10))}


def test_compare_reports_every_metric():
    c = compare(A, B, top=2)
    assert (c.overlap, c.compared) == ((date(2024, 1, 1), date(2024, 1, 6)), 5)
    assert not c.only_a and not c.only_b and not c.misaligned
    assert c.max_abs_diff == pytest.approx(0.02397, abs=1e-5) and c.p99_abs_diff == c.max_abs_diff
    assert len(c.largest) == 2 and [d.day.day for d in c.largest] == [6, 4]  # worst first
    w = c.largest[0]
    assert w.diff == pytest.approx(w.ret_a - w.ret_b) and abs(w.diff) == c.max_abs_diff
    assert c.cumulative_a == pytest.approx(0.03) and c.cumulative_b == pytest.approx(0.06)
    assert -1 <= c.correlation <= 1


def test_a_session_missing_on_one_side_is_not_bridged():
    b = {d: v for d, v in B.items() if d != date(2024, 1, 3)}
    c = compare(A, b)
    assert c.only_a == (date(2024, 1, 3),) and c.only_b == ()
    assert c.misaligned == (date(2024, 1, 4),)  # B's day-4 return spans 2 -> 4, A's spans 3 -> 4
    assert c.compared == 3  # days 2, 5, 6 are comparable


def test_missing_on_the_other_side_is_reported_too():
    a = {d: v for d, v in A.items() if d != date(2024, 1, 2)}
    assert compare(a, B).only_b == (date(2024, 1, 2),)


def test_series_must_overlap_and_have_enough_common_dates():
    with pytest.raises(ValueError, match="do not overlap"):
        compare(s((1, 1), (2, 2)), s((3, 1), (4, 2)))
    with pytest.raises(ValueError, match="fewer than two"):
        compare(s((1, 1), (2, 2)), s((1, 1), (2, 3)))


def test_percentile_and_correlation():
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.0
    assert percentile([5.0], 0.99) == 5.0
    assert percentile([1.0, 2.0], 0.0) == 1.0
    assert correlation([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    assert correlation([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert math.isnan(correlation([1, 1, 1], [1, 2, 3]))
