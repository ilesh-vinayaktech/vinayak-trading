from datetime import UTC, date, datetime

from algo.api.freshness import BASIS, assess

SUN = datetime(2026, 11, 8, 4, 51, tzinfo=UTC)  # Sunday 10:21 IST
NONE: frozenset[date] = frozenset()


def test_on_a_sunday_the_friday_bar_is_current_and_monday_is_next():
    r = assess(date(2026, 11, 6), SUN, NONE)
    assert r == {
        "latest_bar_session": "2026-11-06", "expected_latest_session": "2026-11-06",
        "next_session": "2026-11-09", "sessions_behind": 0, "status": "CURRENT", "basis": BASIS,
    }  # fmt: skip


def test_a_weekday_before_the_publish_time_still_expects_yesterdays_file():
    tue_morning = datetime(2026, 11, 10, 3, 0, tzinfo=UTC)  # 08:30 IST
    r = assess(date(2026, 11, 9), tue_morning, NONE)
    assert r["expected_latest_session"] == "2026-11-09" and r["status"] == "CURRENT"
    assert r["next_session"] == "2026-11-10"


def test_after_the_publish_time_that_days_file_is_expected_and_missing_sessions_are_counted():
    tue_evening = datetime(2026, 11, 10, 14, 0, tzinfo=UTC)  # 19:30 IST
    r = assess(date(2026, 11, 6), tue_evening, NONE)
    assert r["expected_latest_session"] == "2026-11-10"
    assert (r["sessions_behind"], r["status"]) == (2, "BEHIND")  # Nov 9 and Nov 10
    just_before = datetime(2026, 11, 10, 13, 0, tzinfo=UTC)  # 18:30 IST exactly
    assert assess(date(2026, 11, 9), just_before, NONE)["expected_latest_session"] == "2026-11-10"
    assert (
        assess(date(2026, 11, 9), datetime(2026, 11, 10, 12, 59, tzinfo=UTC), NONE)[
            "expected_latest_session"
        ]
        == "2026-11-09"
    )  # 18:29 IST


def test_known_holidays_are_not_sessions():
    hol = frozenset({date(2026, 11, 6), date(2026, 11, 9)})
    r = assess(date(2026, 11, 5), SUN, hol)
    assert r["expected_latest_session"] == "2026-11-05" and r["status"] == "CURRENT"
    assert r["next_session"] == "2026-11-10"  # skips the Monday holiday
    behind = assess(date(2026, 11, 4), SUN, hol)
    assert behind["sessions_behind"] == 1 and behind["status"] == "BEHIND"  # only Nov 5 counts
