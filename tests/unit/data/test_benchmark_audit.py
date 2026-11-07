import math
from datetime import date, time
from decimal import Decimal as D

import pytest

from algo.core.calendar import nse
from algo.data.benchmark_audit import (
    ALIGNMENT_GAP,
    BENCHMARK_ONLY_SESSION,
    CONFIRMED_REGULAR,
    CONFIRMED_SPECIAL,
    DATA_GAP,
    EXPECTED_CLOSED,
    EXPECTED_NO_SESSION,
    INVESTIGATE,
    QUARANTINED_NO_VALUE,
    QUARANTINED_UNRESOLVED,
    UNCONFIRMED_NO_VALUE,
    WEEKDAY_RULE_PROVISIONAL,
    Evidence,
    alignment,
    anomaly_overlap,
    discontinuities,
    missing_outcome,
    net_rises,
    observed_outcome,
    ratio_changes,
    reconcile,
)  # fmt: skip

MON, TUE, WED, SAT, SUN = (date(2024, 1, d) for d in (1, 2, 3, 6, 7))
HOLIDAY = date(2024, 1, 26)  # a Friday
LISTED_SAT, LISTED_WD = date(2024, 1, 13), date(2024, 1, 10)
CAL = nse(
    [HOLIDAY], {LISTED_SAT: (time(9, 15), time(15, 30)), LISTED_WD: (time(9, 15), time(15, 30))}
)
INFO = CAL.session_info
EV = Evidence(
    traded=frozenset({TUE, LISTED_SAT, SAT, HOLIDAY}),
    not_published=frozenset({WED, LISTED_WD}),
    quarantined=frozenset({date(2024, 1, 15)}),
    first=date(2024, 1, 2), last=date(2024, 1, 31),
)  # fmt: skip


@pytest.mark.parametrize(
    ("d", "outcome", "why"),
    [
        (date(2024, 1, 15), QUARANTINED_UNRESOLVED, "bhavcopy quarantined: trading is not independently shown"),
        (LISTED_SAT, CONFIRMED_SPECIAL, "bhavcopy exists; kind and hours remain as listed"),
        (SAT, INVESTIGATE, "bhavcopy exists on a day no session is listed"),
        (HOLIDAY, INVESTIGATE, "bhavcopy exists on a day no session is listed"),
        (TUE, CONFIRMED_REGULAR, "bhavcopy exists on a weekday session"),
        (LISTED_WD, BENCHMARK_ONLY_SESSION, "listed session; the only evidence is the benchmark itself"),
        (SUN, INVESTIGATE, "weekend value with no listed session"),
        (date(2024, 1, 20), INVESTIGATE, "weekend value with no listed session"),  # a Saturday
        (date(2024, 1, 4), WEEKDAY_RULE_PROVISIONAL, "weekday; no independent holiday or trading evidence"),
        (date(2023, 6, 1), WEEKDAY_RULE_PROVISIONAL, "weekday; no independent holiday or trading evidence"),
        (WED, INVESTIGATE, "weekday value but the exchange published no bhavcopy"),
    ],
)  # fmt: skip
def test_every_observed_date_gets_an_explicit_outcome(d, outcome, why):
    assert observed_outcome(d, INFO(d), EV) == (outcome, why)


def test_the_bhavcopy_range_edges_are_inclusive():
    for first, last in ((WED, date(2024, 1, 31)), (date(2024, 1, 2), WED)):
        ev = Evidence(frozenset(), frozenset({WED}), frozenset(), first, last)
        assert observed_outcome(WED, INFO(WED), ev)[0] == INVESTIGATE


def test_a_known_holiday_with_a_value_and_no_bhavcopy_is_investigated():
    ev = Evidence(frozenset(), frozenset(), frozenset(), date(2024, 1, 2), date(2024, 1, 31))
    assert observed_outcome(HOLIDAY, INFO(HOLIDAY), ev) == (INVESTIGATE, "value on a known holiday")


def test_a_not_published_day_outside_the_bhavcopy_range_is_not_held_against_the_benchmark():
    ev = Evidence(
        frozenset(), frozenset({date(2023, 6, 1)}), frozenset(), date(2024, 1, 2), date(2024, 1, 31)
    )
    assert (
        observed_outcome(date(2023, 6, 1), INFO(date(2023, 6, 1)), ev)[0]
        == WEEKDAY_RULE_PROVISIONAL
    )


@pytest.mark.parametrize(
    ("d", "elsewhere", "outcome"),
    [
        (TUE, False, DATA_GAP),  # bhavcopy proves trading
        (TUE, True, DATA_GAP),
        (date(2024, 1, 15), False, QUARANTINED_NO_VALUE),
        (date(2024, 1, 4), True, ALIGNMENT_GAP),
        (WED, False, EXPECTED_CLOSED),  # no bhavcopy published
        (HOLIDAY, False, DATA_GAP),  # traded in this evidence set
        (date(2024, 1, 4), False, UNCONFIRMED_NO_VALUE),
        (SUN, False, EXPECTED_NO_SESSION),
    ],
)
def test_a_missing_value_is_classified_by_the_independent_evidence(d, elsewhere, outcome):
    assert missing_outcome(d, INFO(d), EV, elsewhere) == outcome


def test_a_weekday_holiday_without_a_bhavcopy_is_an_expected_closure_and_a_weekend_holiday_is_not():
    ev = Evidence(frozenset(), frozenset(), frozenset(), date(2024, 1, 2), date(2024, 1, 31))
    assert missing_outcome(HOLIDAY, INFO(HOLIDAY), ev, False) == EXPECTED_CLOSED
    cal = nse([SAT])  # a holiday that is also a Saturday: no extra information, still a weekend
    assert missing_outcome(SAT, cal.session_info(SAT), ev, False) == EXPECTED_NO_SESSION


def lv(*pairs):
    return {date(2024, 1, d): D(str(v)) for d, v in pairs}


def test_reconcile_gives_every_observed_date_an_outcome_and_lists_the_gaps():
    a = lv((2, 100), (3, 101), (4, 102), (8, 103))
    b = lv((2, 50), (4, 51), (6, 52))  # b lacks 3 and 8 inside a's range; has a Saturday value
    r = reconcile({"a": a, "b": b}, INFO, EV)
    assert set(r.observed) == set(a) | set(b)
    assert r.observed[TUE][2] == ("a", "b")
    assert r.observed[date(2024, 1, 3)][0] == INVESTIGATE and r.observed[date(2024, 1, 3)][2] == (
        "a",
    )
    assert r.observed_counts[CONFIRMED_REGULAR] == 1
    assert r.missing["b"] == {  # 8 is outside b's coverage
        ALIGNMENT_GAP: [date(2024, 1, 3)],
        UNCONFIRMED_NO_VALUE: [date(2024, 1, 5)],
    }
    assert r.missing["a"] == {UNCONFIRMED_NO_VALUE: [date(2024, 1, 5)], DATA_GAP: [SAT]}
    assert r.missing_counts["a"][EXPECTED_NO_SESSION] == 1  # the Sunday is counted, not listed
    assert r.missing_counts["a"][DATA_GAP] == 1


def test_alignment_separates_coverage_differences_from_gaps_inside_coverage():
    a = lv((1, 1), (2, 1), (3, 1), (4, 1), (5, 1))
    b = lv((2, 1), (4, 1), (5, 1), (8, 1))
    al = alignment({"a": a, "b": b})
    assert al["a"]["inside_gaps"] == [] and al["a"]["outside_coverage"] == 1
    assert al["a"]["outside_range"] == (date(2024, 1, 8), date(2024, 1, 8))
    assert al["b"]["inside_gaps"] == [date(2024, 1, 3)] and al["b"]["outside_coverage"] == 1
    assert al["b"]["outside_range"] == (date(2024, 1, 1), date(2024, 1, 1))
    assert (al["b"]["first"], al["b"]["last"], al["b"]["observations"]) == (
        date(2024, 1, 2),
        date(2024, 1, 8),
        4,
    )
    assert alignment({"a": a})["a"]["outside_range"] is None


def test_large_moves_are_corroborated_uncorroborated_or_unexplained():
    a = lv((1, 100), (2, 80), (3, 80), (4, 100), (5, 100))
    b = lv((1, 100), (2, 82), (3, 81), (4, 85), (5, 85))
    c = lv((3, 10), (4, 10), (5, 10))
    out = discontinuities({"a": a, "b": b, "c": c})
    by = {(x["series"], x["date"]): x for x in out}
    assert by[("a", date(2024, 1, 2))]["status"] == "CORROBORATED"  # b fell 18%
    assert by[("a", date(2024, 1, 4))]["status"] == "UNEXPLAINED"  # b rose only 4.9%
    assert by[("a", date(2024, 1, 4))]["others"] == pytest.approx({"b": 85 / 81 - 1, "c": 0.0})
    solo = discontinuities({"a": lv((1, 1), (2, 2))})
    assert [x["status"] for x in solo] == ["UNCORROBORATED_SINGLE_SERIES"]
    assert all(abs(x["return"]) >= 0.05 for x in out)
    assert discontinuities({"a": lv((1, 100), (2, 104.9))}) == []  # below the 5% threshold
    wrong = discontinuities({"a": lv((1, 100), (2, 90)), "b": lv((1, 100), (2, 110))})
    assert {x["status"] for x in wrong} == {"UNEXPLAINED"}  # opposite sign
    small = discontinuities({"a": lv((1, 100), (2, 90)), "b": lv((1, 100), (2, 96))})
    assert small[0]["status"] == "UNEXPLAINED"  # same sign but under half the size


def test_net_rises_follow_the_validate_net_definition():
    gross = lv((1, 1000), (2, 1010), (3, 1020), (4, 1030))
    net = lv((1, 1000), (2, 1009), (3, 1020), (4, 1028))
    rises = net_rises(gross, net)
    assert list(rises) == [date(2024, 1, 3)] and rises[date(2024, 1, 3)] > 0
    assert set(ratio_changes(gross, net)) == {date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)}
    assert ratio_changes(gross, net)[date(2024, 1, 3)] == pytest.approx(rises[date(2024, 1, 3)])
    assert net_rises(gross, lv((2, 1010))) == {}  # a single net day has no change


def test_anomaly_overlap_reports_chance_correlation_and_ex_date_shares():
    days = [date(2024, 1, d) for d in range(1, 21)]
    ga = {d: i / 1000 for i, d in enumerate(days)}
    gb = {d: i / 1000 + 0.001 for i, d in enumerate(days)}
    a = {days[i]: ga[days[i]] for i in (3, 5, 7, 9)}
    b = {days[i]: gb[days[i]] for i in (3, 5, 7, 11)}
    ex = frozenset(days[:10])
    o = anomaly_overlap(a, b, ga, gb, ex)
    assert (
        o["intersection"] == [days[3], days[5], days[7]] and o["verdict"] == "OVERLAP_ABOVE_CHANCE"
    )
    assert o["expected_by_chance"] == pytest.approx(4 * 4 / 20)
    assert o["magnitude_correlation_all_common_dates"] == pytest.approx(1.0)
    assert (o["ex_date_share_a"], o["ex_date_share_b"]) == (1.0, 0.75)
    assert o["ex_date_share_all_common_dates"] == 0.5
    assert (o["count_a"], o["count_b"], o["common_comparable_dates"]) == (4, 4, 20)
    far = anomaly_overlap({days[0]: 1.0}, {days[10]: 1.0}, ga, gb, ex)
    assert far["verdict"] == "NO_OVERLAP_BEYOND_CHANCE" and far["intersection"] == []
    empty = anomaly_overlap({}, {}, {}, {}, frozenset())
    assert empty["common_comparable_dates"] == 0 and math.isnan(
        empty["magnitude_correlation_all_common_dates"]
    )
    assert empty["ex_date_share_a"] == 0.0 and empty["ex_date_share_all_common_dates"] == 0.0


def test_a_move_exactly_at_the_threshold_and_a_partner_at_exactly_half_count():
    out = discontinuities(
        {"a": lv((1, 100), (2, 106.25)), "b": lv((1, 100), (2, 103.125))}, threshold=D("0.0625")
    )
    assert [(x["series"], x["status"]) for x in out] == [("a", "CORROBORATED")]
    flat = discontinuities({"a": lv((1, 100), (2, 150)), "b": lv((1, 100), (2, 100))})
    assert flat[0]["status"] == "UNEXPLAINED" and flat[0]["others"] == {"b": 0.0}


def test_net_rises_use_a_relative_tolerance_with_a_strict_boundary():
    gross = lv((1, 1000), (2, 1000), (3, 1000))
    exact = lv((1, 500), (2, 550), (3, 550))  # ratio .5 -> .55: a rise of exactly .1 * .5
    assert net_rises(gross, exact, tol=D("0.1")) == {}
    assert list(net_rises(gross, exact, tol=D("0.05"))) == [date(2024, 1, 2)]
    small = lv((1, 500), (2, 540), (3, 540))  # rise .04 > .05 * .5 but not > .1 / .5
    assert list(net_rises(gross, small, tol=D("0.05"))) == [date(2024, 1, 2)]


def test_overlap_verdict_needs_both_more_than_twice_chance_and_three_shared_days():
    days = [date(2024, 1, d) for d in range(1, 10)]
    g = {d: float(i) for i, d in enumerate(days)}
    pick = lambda idx: {days[i]: 1.0 for i in idx}  # noqa: E731
    # 3 shared of 3/3 anomalies over 9 days: chance exactly 1.0, 2x chance = 2 < 3
    o = anomaly_overlap(pick((0, 1, 2)), pick((0, 1, 2)), g, g, frozenset())
    assert o["expected_by_chance"] == 1.0 and o["verdict"] == "OVERLAP_ABOVE_CHANCE"
    # 3 shared, but chance 4*4/9=1.78: 3 is not more than twice
    o = anomaly_overlap(pick((0, 1, 2, 3)), pick((0, 1, 2, 4)), g, g, frozenset())
    assert o["verdict"] == "NO_OVERLAP_BEYOND_CHANCE"
    # exactly twice chance (1.5 -> 3.0): not strictly more
    g6 = {d: float(i) for i, d in enumerate(days[:6])}
    o = anomaly_overlap(
        {days[i]: 1.0 for i in (0, 1, 2)}, {days[i]: 1.0 for i in (0, 1, 2)}, g6, g6, frozenset()
    )
    assert o["expected_by_chance"] == 1.5 and o["verdict"] == "NO_OVERLAP_BEYOND_CHANCE"
    # two shared days, far above chance, still not enough days
    o = anomaly_overlap(pick((0, 1)), pick((0, 1)), g, g, frozenset())
    assert o["verdict"] == "NO_OVERLAP_BEYOND_CHANCE" and len(o["intersection"]) == 2


def test_overlap_correlation_needs_three_common_dates_and_uses_the_intersection_of_dates():
    days = [date(2024, 1, d) for d in (1, 2, 3, 4)]
    g = {d: float(i) for i, d in enumerate(days)}
    two = anomaly_overlap(
        {}, {}, {days[0]: 1.0, days[1]: 2.0}, {days[0]: 1.0, days[1]: 2.0}, frozenset()
    )
    assert math.isnan(two["magnitude_correlation_all_common_dates"])
    three = anomaly_overlap(
        {}, {}, {d: g[d] for d in days[:3]}, {d: g[d] for d in days[:3]}, frozenset()
    )
    assert three["magnitude_correlation_all_common_dates"] == pytest.approx(1.0)
    partial = anomaly_overlap(
        {}, {}, {d: g[d] for d in days[:3]}, {d: g[d] for d in days[1:]}, frozenset()
    )
    assert partial["common_comparable_dates"] == 2
    ex = anomaly_overlap({}, {}, g, g, frozenset(days[:1]))
    assert ex["ex_date_share_all_common_dates"] == 0.25 and ex["expected_by_chance"] == 0.0
    assert ex["direction"].startswith("both are days on which the less dividend-inclusive")
