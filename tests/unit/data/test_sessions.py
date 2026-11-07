import json
from datetime import date, time

import pytest

from algo.data.sessions import REGULAR_HOURS, build_entries, calendar, load, weekend_sessions


def test_only_weekend_dates_of_a_series_are_extra_sessions():
    days = [
        date(2026, 1, 30),
        date(2026, 1, 31),
        date(2026, 2, 1),
        date(2026, 2, 2),
        date(2026, 2, 1),
    ]
    assert weekend_sessions(days) == [date(2026, 1, 31), date(2026, 2, 1)]
    assert weekend_sessions([]) == []


def test_entries_state_the_evidence_and_what_is_unknown():
    e = build_entries([date(2025, 2, 1), date(2025, 2, 3)], "TRI value on a weekend", "abc")
    assert len(e) == 1
    assert (
        e[0]["date"] == "2025-02-01" and e[0]["weekday"] == "Saturday" and e[0]["kind"] == "SPECIAL"
    )
    assert e[0]["hours"] is None and e[0]["hours_status"].startswith("UNKNOWN")
    assert e[0]["kind_status"].startswith("UNCONFIRMED") and e[0]["evidence_sha256"] == "abc"


def write(tmp_path, sessions):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"sessions": sessions}))
    return p


def test_the_file_feeds_the_calendar_with_default_or_stated_hours(tmp_path):
    p = write(tmp_path, [
        {"date": "2026-02-01", "kind": "SPECIAL", "hours": None},
        {"date": "2021-11-04", "kind": "MUHURAT", "hours": ["18:15", "19:15"]},
    ])  # fmt: skip
    hours, kinds = load(p)
    assert hours[date(2026, 2, 1)] == REGULAR_HOURS and hours[date(2021, 11, 4)] == (
        time(18, 15),
        time(19, 15),
    )
    assert kinds == {date(2026, 2, 1): "SPECIAL", date(2021, 11, 4): "MUHURAT"}
    cal = calendar(p, holidays=[date(2021, 11, 4)])
    assert (
        cal.session_type(date(2026, 2, 1)) == "SPECIAL"
        and cal.session_type(date(2021, 11, 4)) == "MUHURAT"
    )
    assert cal.is_trading_day(date(2026, 2, 1)) and cal.session_type(date(2026, 1, 31)) == "CLOSED"


def test_a_bad_or_duplicated_entry_is_refused(tmp_path):
    with pytest.raises(ValueError, match="kind must be SPECIAL or MUHURAT"):
        load(write(tmp_path, [{"date": "2026-02-01", "kind": "REGULAR"}]))
    with pytest.raises(ValueError, match="listed twice"):
        load(
            write(
                tmp_path,
                [
                    {"date": "2026-02-01", "kind": "SPECIAL"},
                    {"date": "2026-02-01", "kind": "SPECIAL"},
                ],
            )
        )
