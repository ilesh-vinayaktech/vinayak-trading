# ruff: noqa: E501, F811
"""The stored feature values a definition's chart decisions are read from: every stock of the freeze, cut to the development period."""

from datetime import date

import pytest

from algo.data.readiness import Readiness
from algo.factory import generate, signals
from algo.features import job, store
from tests.integration.alpha.test_run import (
    JAN,
    world,  # noqa: F401 - the fixture: 8 stocks, stored ret_5d and ret_20d
)
from tests.integration.features.test_store import NOW

pytestmark = pytest.mark.integration


def with_traded_value(conn, fid):
    """The chart ranks against the most traded names, so traded_value_20d must be stored too."""
    store.set_status(conn, "traded_value_20d", "1", "USABLE", by="owner", reason="test", now=NOW)
    job.run(conn, fid, JAN, NOW, "abc", ready=lambda c, n: Readiness())


DEFN = generate.definition_for(
    generate.Hypothesis(1, 1, "ret_20d", "1", 20, "POSITIVE", 0.05, 0.001)
)


def test_the_values_cover_every_stock_and_stop_at_the_development_end_whatever_range_is_asked(
    world,
):  # noqa: F811
    conn, ids, fid = world
    with_traded_value(conn, fid)
    values, liquid, end = signals.load_values(conn, DEFN, date(2026, 1, 1), date(2026, 3, 31))
    assert end == date(2026, 2, 28)  # the holdout starts 2026-03-01: never read
    per_day = values["ret_20d"]
    assert max(per_day) <= date(2026, 2, 28)
    day = max(per_day)
    assert set(per_day[day]) == set(ids)  # every stock of the freeze has a value that day
    assert liquid[day] == set(ids)  # eight stocks, all within the 200 most traded
    few, liq, _ = signals.load_values(
        conn, DEFN, date(2026, 1, 1), date(2026, 3, 31), top=3, always=ids[0]
    )
    assert len(liq[day]) == 3 and set(few["ret_20d"][day]) == liq[day] | {
        ids[0]
    }  # only the 3 most traded, plus the stock being drawn


def test_a_month_without_a_stored_run_is_refused_with_the_reason_not_guessed(world):  # noqa: F811
    conn, _, fid = world
    with_traded_value(conn, fid)
    with pytest.raises(signals.SignalsError, match="no completed run"):
        signals.load_values(conn, DEFN, date(2025, 6, 1), date(2025, 7, 31))
