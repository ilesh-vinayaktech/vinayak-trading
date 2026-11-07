from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from algo.data.bars import Bar
from algo.data.quality.checks import validity


def bar(o="10", h="12", low="9", c="11", v="100"):
    return Bar("X", datetime(2026, 1, 5, 3, 45, tzinfo=UTC), D(o), D(h), D(low), D(c), D(v))


def test_good_bar_passes():
    assert validity([bar()]) == []


@pytest.mark.parametrize(
    "kw",
    [
        dict(h="10.5"),
        dict(low="10.5"),
        dict(o="0"),
        dict(c="-1"),
        dict(v="-5"),
        dict(h="8", low="9"),
    ],
)
def test_bad_bars_flagged(kw):
    assert validity([bar(**kw)])


def test_boundary_equal_values_ok():
    assert validity([bar("10", "10", "10", "10", "0")]) == []


def test_issue_names_symbol_and_time():
    assert "X 2026-01-05 03:45" in validity([bar(o="0")])[0]
