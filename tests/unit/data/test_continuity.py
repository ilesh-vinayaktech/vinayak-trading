from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

from algo.data.adjust.factors import Adjustment
from algo.data.quality.continuity import continuity_issues

KT = datetime(2025, 1, 1, tzinfo=UTC)
D0 = date(2025, 6, 9)  # Monday


def series(*closes, start=D0):
    out, d = [], start
    for c in closes:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append((d, D(c)))
        d += timedelta(days=1)
    return out


def split(ex, factor):
    return Adjustment(ex, "split", D(factor), KT)


def test_quiet_series_is_clean():
    assert continuity_issues(series(100, 101, 99, 102, 100), []) == []


def test_split_with_matching_price_drop_is_clean():
    s = series(1000, 1010, 100, 101)  # 10:1 on the third day
    assert continuity_issues(s, [split(s[2][0], "0.1")]) == []


def test_split_within_tolerance_of_market_move_is_clean():
    s = series(1000, 108)  # expected 100, market moved +8%
    assert continuity_issues(s, [split(s[1][0], "0.1")]) == []


def test_unexplained_big_move_is_flagged():
    s = series(100, 70)  # -30%, no action recorded: probable unadjusted split / bad data
    (i,) = continuity_issues(s, [])
    assert (i.kind, i.day) == ("unexplained_jump", s[1][0])


def test_move_at_threshold_is_not_flagged_just_beyond_is():
    assert continuity_issues(series(100, 80), []) == []  # exactly -20%
    assert continuity_issues(series(100, 79.9), [])


def test_action_without_any_discontinuity_is_flagged():
    s = series(100, 101, 102)  # a 1:1 bonus (factor 0.5) but the price never halved
    (i,) = continuity_issues(s, [split(s[1][0], "0.5")])
    assert (i.kind, i.day) == ("action_without_discontinuity", s[1][0])


def test_wrong_ratio_is_flagged_as_mismatch():
    s = series(1000, 500)  # price halved, but our factor says 1:5
    (i,) = continuity_issues(s, [split(s[1][0], "0.2")])
    assert i.kind == "action_without_discontinuity"  # the recorded action does not explain the move


def test_ex_date_on_a_non_session_day_applies_to_the_next_bar():
    fri, mon = date(2025, 6, 13), date(2025, 6, 16)
    s = [(fri, D(1000)), (mon, D(100))]
    assert continuity_issues(s, [split(date(2025, 6, 14), "0.1")]) == []  # Saturday ex-date


def test_dividends_are_ignored_by_the_check():
    s = series(100, 99)
    assert continuity_issues(s, [Adjustment(s[1][0], "dividend", D("0.99"), KT)]) == []


def test_two_actions_same_day_multiply():
    s = series(9331, 938)  # Bajaj 2025: bonus 4:1 and 2:1 split
    adj = [split(s[1][0], "0.2"), split(s[1][0], "0.5")]
    assert continuity_issues(s, adj) == []


def test_short_or_empty_series_has_no_issues():
    assert continuity_issues([], []) == [] and continuity_issues(series(100), []) == []


def test_price_only_adjustments_explain_a_move_just_like_splits():
    """A resolved demerger factor is kind 'price'; without it the drop is an unexplained jump."""
    s = series(1000, 900)
    price = Adjustment(s[1][0], "price", D("0.9"), KT)
    assert continuity_issues(s, [price]) == []
    assert [i.kind for i in continuity_issues(s, [])] == []  # -10% is under the 20% threshold
    big = series(1000, 600)
    assert continuity_issues(big, [Adjustment(big[1][0], "price", D("0.6"), KT)]) == []
    assert [i.kind for i in continuity_issues(big, [])] == ["unexplained_jump"]


def test_the_tolerance_boundary_is_inclusive():
    s = series(1000, 125)  # expected x0.1 -> observed x0.125 => exactly 25% off
    assert continuity_issues(s, [split(s[1][0], "0.1")]) == []
    s2 = series(1000, 126)
    assert [i.kind for i in continuity_issues(s2, [split(s2[1][0], "0.1")])] == [
        "action_without_discontinuity"
    ]


def test_issue_details_name_the_numbers():
    s = series(100, 70)
    assert continuity_issues(s, [])[0].detail == "close-to-close x0.7000"
    t = series(100, 101)
    assert continuity_issues(t, [split(t[1][0], "0.5")])[0].detail == "expected x0.5000, saw x1.0100"
