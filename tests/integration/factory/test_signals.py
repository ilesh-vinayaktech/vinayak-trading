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


def test_the_stored_window_stops_at_the_development_end_and_the_values_are_kept_for_the_most_traded_names(
    world,
):  # noqa: F811
    conn, ids, fid = world
    with_traded_value(conn, fid)
    got = signals.load_values(conn, DEFN, date(2026, 1, 1), date(2026, 3, 31))
    assert got.last == date(2026, 2, 28)  # the holdout starts 2026-03-01: not in the stored window
    per_day = got.values["ret_20d"]
    assert max(per_day) <= date(2026, 2, 28)
    day = max(per_day)
    assert set(per_day[day]) == set(ids)  # every stock of the freeze has a value that day
    assert got.tail_universe == set(ids)  # eight stocks, all within the 200 most traded
    few = signals.load_values(conn, DEFN, date(2026, 1, 1), date(2026, 3, 31), top=3, always=ids[0])
    assert len(few.tail_universe) == 3 and set(few.values["ret_20d"][day]) == few.tail_universe | {
        ids[0]
    }  # only the 3 most traded, plus the stock being drawn


def test_a_request_wholly_outside_the_stored_window_has_no_stored_values_but_still_names_the_universe_to_compute_for(
    world,
):  # noqa: F811
    conn, ids, fid = world
    with_traded_value(conn, fid)
    got = signals.load_values(conn, DEFN, date(2026, 3, 2), date(2026, 3, 6))
    assert (
        got.values["ret_20d"] == {}
        and got.last == date(2026, 2, 28)
        and got.tail_universe == set(ids)
    )


def test_a_month_without_a_stored_run_is_refused_with_the_reason_not_guessed(world):  # noqa: F811
    conn, _, fid = world
    with pytest.raises(signals.SignalsError, match="no stored values"):
        signals.load_values(
            conn, DEFN, date(2025, 6, 1), date(2025, 7, 31)
        )  # traded_value_20d was never computed here


def test_without_a_data_freeze_there_are_no_stored_values_and_the_reason_is_given(conn):
    from algo.data.store.migrate import migrate
    from tests.support.research_lock import anchor_open_lock

    migrate(conn)
    anchor_open_lock(conn)
    with pytest.raises(signals.SignalsError, match="no data freeze"):
        signals.load_values(conn, DEFN, date(2026, 1, 1), date(2026, 1, 31))


def test_decisions_are_computed_for_days_before_and_after_the_stored_window_without_storing_anything(
    world,
):  # noqa: F811
    """The chart asks for 2025-12-01..2026-03-06 over data stored only for 2026-01..02: the days outside it are computed from the bars on the spot."""

    from algo.data.reader import BarReader

    conn, ids, fid = world
    with_traded_value(conn, fid)
    days = [
        d
        for (d,) in conn.execute(
            "SELECT DISTINCT (ts AT TIME ZONE 'Asia/Kolkata')::date FROM bar_1d WHERE instrument_id=%s ORDER BY 1",
            (ids[0],),
        ).fetchall()
    ]
    reader = BarReader(conn)

    def bars_of(iid, lo, hi):
        return list(reader.history(iid, lo, hi, adjust="split").bars)

    before = conn.execute("SELECT count(*) FROM feature_run").fetchone()
    got = signals.compute(conn, DEFN, ids[0], days, bars_of)
    assert len(got) == len(days) and any(g.ready for g in got)
    assert days[0] < date(2026, 1, 1) < date(2026, 2, 28) < days[-1] or days[-1] > date(
        2026, 2, 28
    )  # the request reaches past the stored window
    assert (
        conn.execute("SELECT count(*) FROM feature_run").fetchone() == before
    )  # nothing was stored
    assert signals.compute(conn, DEFN, ids[0], [], bars_of) == []
