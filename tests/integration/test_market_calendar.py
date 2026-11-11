from datetime import UTC, date, datetime, time, timedelta

import pytest

from algo.data.store.migrate import migrate
from algo.live.market_calendar import (
    CalendarError,
    add_session,
    list_exceptions,
    mark_closed,
    remove,
    windows_for,
)

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 12, 4, 0, tzinfo=UTC)
THU, SAT, MON = date(2026, 11, 12), date(2026, 11, 14), date(2026, 11, 16)


@pytest.fixture
def db(conn):
    migrate(conn)
    return conn


def ist(day: date, hh: int, mm: int) -> datetime:
    return datetime.fromisoformat(f"{day}T{hh:02d}:{mm:02d}:00+05:30").astimezone(UTC)


def session(db, day, start, end, note="x"):
    return add_session(
        db, day=day, start=start, end=end, note=note, source="manual", actor=None, now=NOW
    )


def closed(db, day, note="holiday"):
    return mark_closed(db, day=day, note=note, source="nse", actor=None, now=NOW)


def test_an_ordinary_weekday_has_the_regular_session_and_a_weekend_has_none(db):
    assert windows_for(db, THU) == [(ist(THU, 9, 15), ist(THU, 15, 30))]
    assert windows_for(db, SAT) == []


def test_a_closed_day_has_no_window_and_can_be_reopened_by_removing_the_entry(db):
    cid = closed(db, THU, "Diwali Balipratipada")
    assert windows_for(db, THU) == []
    remove(db, cid)
    assert windows_for(db, THU) == [(ist(THU, 9, 15), ist(THU, 15, 30))]


def test_a_special_session_replaces_the_rule_even_on_a_weekend_or_a_listed_holiday(db):
    session(db, SAT, time(9, 15), time(10, 0), "Special live session")
    assert windows_for(db, SAT) == [(ist(SAT, 9, 15), ist(SAT, 10, 0))]
    closed(db, THU, "Laxmi Pujan")
    session(db, THU, time(18, 15), time(19, 15), "Muhurat")
    assert windows_for(db, THU) == [(ist(THU, 18, 15), ist(THU, 19, 15))]


def test_a_day_can_have_two_windows_in_time_order(db):
    session(db, MON, time(18, 0), time(19, 0), "evening")
    session(db, MON, time(9, 0), time(10, 0), "morning")
    assert [w[0] for w in windows_for(db, MON)] == [ist(MON, 9, 0), ist(MON, 18, 0)]


@pytest.mark.parametrize(
    ("start", "end", "why"),
    [
        (time(10, 0), time(10, 0), "start before end"),
        (time(11, 0), time(10, 0), "start before end"),
        (time(9, 30), time(10, 30), "overlaps"),  # the 09:00 to 10:00 window already there
    ],
)
def test_nonsense_windows_are_refused_with_a_reason(db, start, end, why):
    session(db, MON, time(9, 0), time(10, 0))
    with pytest.raises(CalendarError, match=why):
        session(db, MON, start, end, "y")


def test_closing_a_day_twice_and_removing_a_missing_entry_are_handled(db):
    a = closed(db, THU, "one")
    assert closed(db, THU, "two") == a  # still one entry
    with pytest.raises(CalendarError, match="no such entry"):
        remove(db, 999_999)


def test_the_exceptions_list_is_what_the_calendar_page_shows_in_date_order(db):
    closed(db, MON, "Guru Nanak Jayanti")
    sid = session(db, SAT, time(9, 15), time(10, 0), "drill")
    rows = list_exceptions(db, THU, MON + timedelta(days=1))
    assert [(r["day"], r["kind"]) for r in rows] == [(SAT, "SESSION"), (MON, "CLOSED")]
    assert rows[0] == {
        "id": sid,
        "day": SAT,
        "kind": "SESSION",
        "start": time(9, 15),
        "end": time(10, 0),
        "note": "drill",
        "source": "manual",
        "needs_times": False,
    }
    assert list_exceptions(db, date(2027, 1, 1), date(2027, 2, 1)) == []
