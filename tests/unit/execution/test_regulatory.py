from datetime import date, timedelta

from algo.execution.regulatory import REQUIRED, Item, problems

TODAY = date(2026, 11, 16)


def item(topic, verified=TODAY, effective=date(2026, 4, 1), exchange="NSE", segment="CM"):
    return Item(exchange, segment, topic, {"v": 1}, effective, "NSE circular", verified, "owner")


def all_current(**over):
    return [item(t, **over) for t in REQUIRED]


def test_everything_recorded_and_recently_verified_blocks_nothing():
    assert problems(all_current(), TODAY) == []
    assert (
        problems(all_current(verified=TODAY - timedelta(days=30)), TODAY) == []
    )  # the last allowed day


def test_an_empty_table_blocks_live_and_names_every_missing_rule():
    out = problems([], TODAY)
    assert len(out) == len(REQUIRED) and all("is not recorded for NSE CM" in m for m in out)


def test_one_rule_not_verified_for_over_thirty_days_blocks_only_that_rule():
    items = [item(t) for t in REQUIRED[1:]] + [
        item(REQUIRED[0], verified=TODAY - timedelta(days=31))
    ]
    (only,) = problems(items, TODAY)
    assert REQUIRED[0] in only and "last verified 2026-10-16" in only


def test_a_rule_that_is_not_in_force_yet_or_is_for_another_segment_does_not_count():
    assert len(problems(all_current(effective=TODAY + timedelta(days=1)), TODAY)) == len(REQUIRED)
    assert len(problems(all_current(segment="FO"), TODAY)) == len(REQUIRED)
    assert problems(all_current(segment="FO"), TODAY, segment="FO") == []
