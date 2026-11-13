from datetime import UTC, date, datetime

from algo.data.corporate_actions import refreshed_on
from algo.data.lake import LocalLake

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def test_a_symbol_counts_as_refreshed_only_when_its_newest_raw_file_is_from_that_day(tmp_path):
    lake = LocalLake(tmp_path)
    lake.put("nse", "corporate_actions_TODAYCO", date(2026, 11, 13), b"[]", url="u", fetched_at=NOW)
    lake.put("nse", "corporate_actions_OLDCO", date(2026, 11, 6), b"[]", url="u", fetched_at=NOW)
    lake.put("nse", "corporate_actions_BOTH", date(2026, 11, 6), b"[]", url="u", fetched_at=NOW)
    lake.put("nse", "corporate_actions_BOTH", date(2026, 11, 13), b"[1]", url="u", fetched_at=NOW)
    day = date(2026, 11, 13)
    assert refreshed_on(lake, "TODAYCO", day) is True
    assert refreshed_on(lake, "BOTH", day) is True  # the newest partition decides
    assert refreshed_on(lake, "OLDCO", day) is False  # downloaded a week ago
    assert refreshed_on(lake, "NEVER", day) is False  # no folder at all
