from datetime import date
from decimal import Decimal as D

import pytest

from algo.data.benchmark import BenchmarkError, aligned_returns, missing_sessions

D1, D2, D3 = date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)


def test_returns_come_from_consecutive_levels_with_the_first_day_as_base():
    lv = {D1: D(100), D2: D(110), D3: D(99)}
    assert aligned_returns(lv, [D1, D2, D3]) == pytest.approx([0.1, -0.1])
    assert aligned_returns(lv, [D1]) == []


def test_a_missing_date_is_an_error_not_an_interpolation():
    with pytest.raises(BenchmarkError, match=r"no level for 1 date\(s\)"):
        aligned_returns({D1: D(100), D3: D(99)}, [D1, D2, D3])


def test_days_must_be_strictly_increasing():
    lv = {D1: D(100), D2: D(110)}
    with pytest.raises(BenchmarkError, match="strictly increasing"):
        aligned_returns(lv, [D2, D1])
    with pytest.raises(BenchmarkError, match="strictly increasing"):
        aligned_returns(lv, [D1, D1])


def test_missing_sessions_lists_the_gaps():
    assert missing_sessions({D1: D(1), D3: D(1)}, [D1, D2, D3]) == [D2]
