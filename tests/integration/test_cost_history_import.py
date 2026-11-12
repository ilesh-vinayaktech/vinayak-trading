"""The real cost schedule files (config/cost_schedules) imported into the database: delivery charges for any trade date 2016 on."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from algo.backtest.costs.schedule_store import import_files, list_schedules, load_book
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
CONFIG = Path(__file__).resolve().parents[2] / "config/cost_schedules"
NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)
ALL = ("verified", "extracted_unverified", "assumed_backfill")


@pytest.fixture
def seeded(conn):
    migrate(conn)
    assert import_files(conn, CONFIG, now=NOW) == 10  # 8 delivery periods + 2 intraday
    return conn


def test_importing_again_changes_nothing(seeded):
    assert import_files(seeded, CONFIG, now=NOW) == 0
    assert len(list_schedules(seeded)) == 10


def test_a_study_pricing_any_day_since_2016_finds_the_schedule_in_force_that_day(seeded):
    book = load_book(seeded, "zerodha", ALL)
    expect = {
        date(2016, 1, 1): "nse-cash-delivery-zerodha-2016-01-01",
        date(2019, 10, 1): "nse-cash-delivery-zerodha-2017-07-01",
        date(2022, 7, 18): "nse-cash-delivery-zerodha-2022-07-18",
        date(2023, 5, 2): "nse-cash-delivery-zerodha-2023-04-01",
        date(2024, 4, 1): "nse-cash-delivery-zerodha-2024-04-01",
        date(2025, 6, 9): "nse-cash-delivery-zerodha-2024-10-01",
        date(2026, 3, 1): "nse-cash-delivery-zerodha-2026-03-01",
    }
    for day, schedule_id in expect.items():
        assert book.for_date(day, "DELIVERY").id == schedule_id, day
    cover = book.coverage("DELIVERY")
    assert all(
        a is not None and a + timedelta(days=1) == b
        for (_, a), (b, _) in zip(cover, cover[1:], strict=False)
    )


def test_every_study_day_has_a_schedule_so_no_run_can_stop_for_want_of_one(seeded):
    book = load_book(seeded, "zerodha", ALL)
    day = date(2016, 1, 1)
    while day <= date(2026, 11, 12):
        book.for_date(day, "DELIVERY")  # raises NoScheduleForDate on a gap
        day += timedelta(days=17)  # a stride that lands on every period at least once
