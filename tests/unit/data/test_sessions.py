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


def ent(day, kind="SPECIAL", ks="UNCONFIRMED (x)", hs="UNKNOWN (y)", hours=None):
    return {"date": day, "kind": kind, "kind_status": ks, "hours_status": hs, "hours": hours}


def test_the_file_feeds_the_calendar_with_default_or_stated_hours(tmp_path):
    p = write(tmp_path, [
        ent("2026-02-01"),
        ent("2021-11-04", "MUHURAT", "CONFIRMED (z)", "VERIFIED (w)", ["18:15", "19:15"]),
    ])  # fmt: skip
    hours, kinds, status = load(p)
    assert hours[date(2026, 2, 1)] == REGULAR_HOURS and hours[date(2021, 11, 4)] == (
        time(18, 15),
        time(19, 15),
    )
    assert kinds == {date(2026, 2, 1): "SPECIAL", date(2021, 11, 4): "MUHURAT"}
    assert status[date(2026, 2, 1)] == ("UNCONFIRMED", "UNKNOWN")
    cal = calendar(p, holidays=[date(2021, 11, 4)])
    assert (
        cal.session_type(date(2026, 2, 1)) == "SPECIAL"
        and cal.session_type(date(2021, 11, 4)) == "MUHURAT"
    )
    assert cal.is_trading_day(date(2026, 2, 1)) and cal.session_type(date(2026, 1, 31)) == "CLOSED"


def test_session_info_keeps_existence_kind_hours_and_visibility_apart(tmp_path):
    p = write(tmp_path, [
        ent("2026-02-01"),
        ent("2021-11-04", "MUHURAT", "CONFIRMED (z)", "VERIFIED (w)", ["18:15", "19:15"]),
    ])  # fmt: skip
    cal = calendar(p, holidays=[date(2021, 11, 4), date(2026, 1, 26)])
    unk = cal.session_info(date(2026, 2, 1))  # evidenced, but kind and hours are not
    assert (unk.existence, unk.kind_status, unk.hours, unk.hours_status, unk.bar_visibility) == (
        "EVIDENCED", "UNCONFIRMED", None, "UNKNOWN", "ASSUMPTION")  # fmt: skip
    ver = cal.session_info(date(2021, 11, 4))
    assert (ver.session_type, ver.kind_status, ver.hours, ver.hours_status, ver.bar_visibility) == (
        "MUHURAT", "CONFIRMED", (time(18, 15), time(19, 15)), "VERIFIED", "RULE")  # fmt: skip
    reg = cal.session_info(date(2026, 1, 27))
    assert (reg.existence, reg.hours, reg.hours_status) == ("RULE", REGULAR_HOURS, "RULE")
    for closed in (date(2026, 1, 26), date(2026, 1, 31)):
        c = cal.session_info(closed)
        assert (c.session_type, c.existence, c.hours, c.bar_visibility) == (
            "CLOSED", "NONE", None, "RULE")  # fmt: skip


def test_a_session_without_status_data_defaults_to_unconfirmed_and_unknown():
    from algo.core.calendar import nse

    i = nse([], {date(2026, 2, 1): REGULAR_HOURS}).session_info(date(2026, 2, 1))
    assert (i.kind_status, i.hours_status, i.bar_visibility) == (
        "UNCONFIRMED",
        "UNKNOWN",
        "ASSUMPTION",
    )


def test_provisional_hours_cannot_pass_as_verified(tmp_path):
    with pytest.raises(ValueError, match="exactly when hours_status is VERIFIED or OBSERVED"):
        load(write(tmp_path, [ent("2026-02-01", hours=["10:00", "11:00"])]))
    with pytest.raises(ValueError, match="exactly when hours_status is VERIFIED or OBSERVED"):
        load(write(tmp_path, [ent("2026-02-01", hs="VERIFIED (q)")]))
    with pytest.raises(ValueError, match="hours_status must start with"):
        load(write(tmp_path, [ent("2026-02-01", hs="PROBABLY")]))
    with pytest.raises(ValueError, match="kind_status must start with"):
        load(write(tmp_path, [ent("2026-02-01", ks="")]))


def test_a_bad_or_duplicated_entry_is_refused(tmp_path):
    with pytest.raises(ValueError, match="kind must be SPECIAL or MUHURAT"):
        load(write(tmp_path, [ent("2026-02-01", "REGULAR")]))
    with pytest.raises(ValueError, match="listed twice"):
        load(write(tmp_path, [ent("2026-02-01"), ent("2026-02-01")]))


def test_observed_intervals_join_busy_minutes_drop_a_thin_tail_and_keep_a_gap():
    from datetime import time

    from algo.data.sessions import observed_intervals

    def run(a, b, n):  # one bar per minute from a to b (exclusive), n instruments each
        return {time(m // 60, m % 60): n for m in range(a * 60, b * 60)}

    assert observed_intervals({}) == []
    muhurat = run(18, 19, 300) | {
        time(19, m): 17 for m in range(0, 15)
    }  # 17 stragglers after 19:00
    assert observed_intervals(muhurat) == [(time(18, 0), time(19, 0))]
    split = {time(9, m): 400 for m in range(15, 60)}
    split |= {time(11, m): 400 for m in range(30, 60)} | {time(12, m): 400 for m in range(30)}
    assert observed_intervals(split) == [(time(9, 15), time(10, 0)), (time(11, 30), time(12, 30))]
    assert observed_intervals({time(23, 59): 5}) == [
        (time(23, 59), time(0, 0))
    ]  # closes at midnight


def test_observed_hours_are_used_for_bars_but_are_not_called_verified(tmp_path):
    f = write(
        tmp_path,
        [
            ent(
                "2024-11-01",
                "MUHURAT",
                "OBSERVED (no circular)",
                "OBSERVED (bars)",
                ["18:00", "19:00"],
            )
        ],
    )
    i = calendar(f).session_info(date(2024, 11, 1))
    assert (i.kind_status, i.hours, i.hours_status, i.bar_visibility) == (
        "OBSERVED", (time(18, 0), time(19, 0)), "OBSERVED", "OBSERVED")  # fmt: skip
