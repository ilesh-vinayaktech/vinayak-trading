from decimal import Decimal as D

import pytest
from hypothesis import given
from hypothesis import strategies as st

from algo.core.money import snap_down, snap_nearest

vals = st.decimals(min_value=D("0"), max_value=D("1000000"), places=4, allow_nan=False)
steps = st.sampled_from([D("0.05"), D("0.01"), D("1"), D("0.00001"), D("25")])


@given(vals, steps)
def test_snap_down_never_exceeds_and_is_idempotent(v, s):
    r = snap_down(v, s)
    assert r <= v and v - r < s and snap_down(r, s) == r and r % s == 0


@given(vals, steps)
def test_snap_nearest_within_half_step_and_idempotent(v, s):
    r = snap_nearest(v, s)
    assert abs(r - v) <= s / 2 and snap_nearest(r, s) == r and r % s == 0


def test_tick_example():
    assert snap_nearest(D("100.07"), D("0.05")) == D("100.05")
    assert snap_down(D("7.9"), D("1")) == D("7")


@pytest.mark.parametrize("bad", [D("0"), D("-1")])
def test_bad_step(bad):
    with pytest.raises(ValueError, match="^step must be positive$"):
        snap_down(D("1"), bad)
