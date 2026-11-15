import math
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from algo.paper import tracking

D0 = date(2026, 11, 2)


def curve(*vals, start=D0):
    return {start + timedelta(days=i): D(v) for i, v in enumerate(vals)}


def test_identical_curves_have_no_tracking_error_and_no_gap():
    c = curve(100, 101, 103, 102)
    r = tracking.compare(c, c)
    assert (r.days, r.tracking_error, r.max_daily_gap, r.final_gap) == (3, 0, 0, 0)
    assert r.live_return == r.model_return == D(102) / D(100) - 1


def test_hand_computed_gap_and_tracking_error():
    live = curve(100, 102, 101)  # +2%, -0.980392%
    model = curve(100, 101, 103)  # +1%, +1.980198%
    r = tracking.compare(live, model)
    diffs = [0.02 - 0.01, (101 / 102 - 1) - (103 / 101 - 1)]
    mean = sum(diffs) / 2
    sd = math.sqrt(sum((x - mean) ** 2 for x in diffs) / 1)
    assert r.days == 2
    assert r.tracking_error == pytest.approx(sd * math.sqrt(252))
    assert r.max_daily_gap == pytest.approx(max(abs(x) for x in diffs))
    assert r.final_gap == pytest.approx(
        float(D(101) / D(100) - D(103) / D(100))
    )  # live return minus model return, both from 100


def test_only_the_overlapping_days_are_compared_and_both_are_rebased_to_the_first_common_day():
    live = curve(1000, 1010, 1020, 1030, start=D0)
    model = curve(50, 50.5, 51, start=D0 + timedelta(days=1))  # starts a day later, different scale
    r = tracking.compare(live, model)
    assert r.first == D0 + timedelta(days=1) and r.last == D0 + timedelta(days=3) and r.days == 2
    assert r.live_return == D(1030) / D(1010) - 1 and r.model_return == D("51") / D("50") - 1


def test_too_little_overlap_is_reported_as_such_not_as_zero_error():
    assert tracking.compare(curve(100), curve(100)).tracking_error is None
    assert (
        tracking.compare(curve(100, 101), curve(100, 101)).tracking_error is None
    )  # one return: no deviation to measure
    none = tracking.compare(
        curve(100, 101, 102), curve(100, 101, 102, start=D0 + timedelta(days=30))
    )
    assert none.days == 0 and none.first is None and none.live_return is None


def test_a_flag_is_raised_only_beyond_the_allowed_tracking_error():
    live, model = curve(100, 102, 101, 104), curve(100, 101, 102, 103)
    r = tracking.compare(live, model)
    assert tracking.breached(r, max_tracking_error=0.0001) is True
    assert tracking.breached(r, max_tracking_error=10) is False
    assert (
        tracking.breached(tracking.compare(curve(100), curve(100)), max_tracking_error=0.0) is False
    )  # nothing to judge yet
