import json
from datetime import UTC, date, datetime, time

import pytest

from algo.data.store.migrate import migrate
from algo.live.calendar_sync import sync_holidays
from algo.live.market_calendar import add_session, list_exceptions, windows_for

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 12, 4, 0, tzinfo=UTC)
TODAY = date(2026, 11, 12)


def holiday_master(*rows):
    return json.dumps(
        {
            "CM": [
                {
                    "tradingDate": d.strftime("%d-%b-%Y"),
                    "weekDay": d.strftime("%A"),
                    "description": desc,
                }
                for d, desc in rows
            ]
        }
    ).encode()


RAW = holiday_master(
    (date(2026, 11, 8), "Diwali Laxmi Pujan*"),  # already past: left alone
    (date(2026, 11, 20), "Guru Nanak Jayanti"),
    (date(2026, 11, 21), "Special Muhurat*"),  # a Saturday whose hours NSE announces later
    (date(2026, 12, 25), "Christmas"),
)


@pytest.fixture
def db(conn):
    migrate(conn)
    return conn


def test_upcoming_holidays_are_closed_days_and_starred_ones_are_flagged_as_needing_times(db):
    r = sync_holidays(db, RAW, today=TODAY, now=NOW)
    assert (r.closed, r.needs_times) == (3, [date(2026, 11, 21)])
    assert windows_for(db, date(2026, 11, 20)) == [] and windows_for(db, date(2026, 12, 25)) == []
    rows = {x["day"]: x for x in list_exceptions(db, TODAY, date(2027, 1, 1))}
    assert set(rows) == {date(2026, 11, 20), date(2026, 11, 21), date(2026, 12, 25)}
    assert rows[date(2026, 11, 21)]["needs_times"] is True
    assert rows[date(2026, 11, 20)]["needs_times"] is False
    assert rows[date(2026, 11, 20)]["note"] == "Guru Nanak Jayanti"
    assert rows[date(2026, 11, 20)]["source"] == "nse"


def test_a_sync_can_be_repeated_and_never_disturbs_sessions_added_by_hand(db):
    sync_holidays(db, RAW, today=TODAY, now=NOW)
    add_session(
        db,
        day=date(2026, 11, 21),
        start=time(9, 15),
        end=time(10, 0),
        note="Muhurat",
        source="manual",
        actor=None,
        now=NOW,
    )
    r = sync_holidays(db, RAW, today=TODAY, now=NOW)
    assert r.needs_times == []  # its hours are known now
    assert windows_for(db, date(2026, 11, 21)) == [
        (datetime(2026, 11, 21, 3, 45, tzinfo=UTC), datetime(2026, 11, 21, 4, 30, tzinfo=UTC))
    ]
    assert len(list_exceptions(db, TODAY, date(2027, 1, 1))) == 4  # 3 closed rows + the manual one
