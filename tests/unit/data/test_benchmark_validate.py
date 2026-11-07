from datetime import date
from decimal import Decimal as D

import pytest

from algo.data.benchmark_validate import (
    ReturnCheck,
    WindowResponse,
    compare_sessions,
    reconcile_returns,
    validate_series,
)  # fmt: skip
from algo.data.providers.niftyindices_tri import Observation

B = date(2004, 1, 1)


def ob(d, v):
    return Observation(d, D(str(v)), None)


def win(s, e, *obs):
    return WindowResponse(s, e, tuple(obs))


def check(v, name):
    return next(c for c in v.checks if c.name == name)


def test_a_clean_series_passes_and_keeps_its_levels_and_largest_moves():
    r = [
        win(
            B,
            date(2004, 12, 30),
            ob(B, "1000.00"),
            ob(date(2004, 1, 2), "1010.00"),
            ob(date(2004, 1, 5), "1000.00"),
        )
    ]
    v = validate_series(r, base_date=B, base_level=D("1000.00"))
    assert v.passed and v.failures() == [] and len(v.levels) == 3 and v.gaps == []
    assert v.largest_moves[0][1] == date(2004, 1, 2)
    assert float(v.largest_moves[0][0]) == pytest.approx(0.01)


def test_wrong_first_date_or_base_level_fails_with_the_values_named():
    v = validate_series(
        [win(B, B, ob(date(2004, 1, 2), "999.00"))], base_date=B, base_level=D("1000.00")
    )
    assert (
        not check(v, "first_observation").passed
        and "2004-01-02" in check(v, "first_observation").detail
    )
    assert not check(v, "base_level").passed and "999.00" in check(v, "base_level").detail


def test_duplicates_are_reported_and_conflicting_values_are_never_resolved():
    a = win(B, date(2004, 6, 30), ob(B, "1000.00"), ob(date(2004, 1, 2), "1010.00"))
    b = win(
        date(2004, 1, 2),
        date(2004, 12, 31),
        ob(date(2004, 1, 2), "1010.00"),
        ob(date(2004, 1, 5), "1020.00"),
    )
    same = validate_series([a, b], base_date=B, base_level=D("1000.00"))
    assert not check(same, "duplicate_dates").passed and check(same, "conflicting_values").passed
    assert same.levels[date(2004, 1, 2)] == D("1010.00")  # identical overlap is consistent
    c = win(date(2004, 1, 2), date(2004, 12, 31), ob(date(2004, 1, 2), "1011.00"))
    conflict = validate_series([a, c], base_date=B, base_level=D("1000.00"))
    assert (
        not check(conflict, "conflicting_values").passed
        and "2004-01-02" in check(conflict, "conflicting_values").detail
    )
    assert (
        conflict.levels == {} and conflict.largest_moves == []
    )  # no series is produced from a conflict


def test_rows_outside_their_window_and_non_positive_levels_fail():
    v = validate_series([win(B, date(2004, 1, 3), ob(B, "1000.00"), ob(date(2004, 2, 1), "0.00"))],
                        base_date=B, base_level=D("1000.00"))  # fmt: skip
    assert not check(v, "inside_requested_window").passed and not check(v, "positive_levels").passed


def test_gaps_over_the_threshold_are_listed_not_filled():
    v = validate_series([win(B, date(2004, 3, 1), ob(B, "1000.00"), ob(date(2004, 1, 20), "1001.00"))],
                        base_date=B, base_level=D("1000.00"))  # fmt: skip
    assert v.gaps == [(B, date(2004, 1, 20))] and len(v.levels) == 2
    assert validate_series([win(B, B, ob(B, "1000.00"), ob(date(2004, 1, 6), "1001.00"))], base_date=B,
                           base_level=D("1000.00"), gap_days=5).gaps == []  # exactly 5 days is allowed  # fmt: skip


def test_an_empty_response_is_a_failure():
    v = validate_series([win(B, B)], base_date=B, base_level=D("1000.00"))
    assert not v.passed and check(v, "not_empty").detail == "no observations"


def test_dates_are_compared_with_a_calendar_in_both_directions():
    extra, missing = compare_sessions(
        [date(2026, 2, 1), date(2026, 2, 2)], [date(2026, 2, 2), date(2026, 2, 3)]
    )
    assert extra == [date(2026, 2, 1)] and missing == [date(2026, 2, 3)]


def test_published_returns_are_recomputed_with_a_stated_convention_and_tolerance():
    lv = {date(2020, 1, 1): D("100"), date(2021, 1, 1): D("110"), date(2025, 1, 1): D("161.051")}
    cum = ReturnCheck(
        "1y", date(2020, 1, 1), date(2021, 1, 1), "cumulative", D("10.00"), D("0.005")
    )
    cagr = ReturnCheck("5y", date(2020, 1, 1), date(2025, 1, 1), "cagr", D("10.00"), D("0.02"))
    off = ReturnCheck(
        "bad", date(2020, 1, 1), date(2021, 1, 1), "cumulative", D("11.00"), D("0.005")
    )
    r = reconcile_returns(lv, [cum, cagr, off])
    assert [x.passed for x in r] == [True, True, False]
    assert float(r[0].computed_pct) == pytest.approx(10.0) and float(
        r[2].difference_pp
    ) == pytest.approx(-1.0)
    with pytest.raises(KeyError, match="no level for 2022-01-01"):
        reconcile_returns(
            lv, [ReturnCheck("x", date(2020, 1, 1), date(2022, 1, 1), "cumulative", D(1), D(1))]
        )
    with pytest.raises(ValueError, match="unknown return kind"):
        reconcile_returns(
            lv, [ReturnCheck("x", date(2020, 1, 1), date(2021, 1, 1), "weird", D(1), D(1))]
        )


# ---- net total-return validation ------------------------------------------------------------------
from algo.data.benchmark_validate import validate_net  # noqa: E402

D1, D2, D3, D4 = date(2000, 1, 3), date(2000, 1, 4), date(2000, 1, 5), date(2000, 1, 6)


def lv(**kw):
    return {d: D(str(v)) for d, v in kw.items()}


def test_a_base_level_of_none_is_not_checked_but_the_first_date_still_is():
    v = validate_series([win(B, B, ob(B, "1256.38"))], base_date=B, base_level=None)
    assert v.passed and "base_level" not in {c.name for c in v.checks}


def test_a_consistent_net_series_passes_every_check():
    gross = {D1: D("1000.00"), D2: D("1010.00"), D3: D("1020.00"), D4: D("1030.00")}
    net = {
        D1: D("1000.00"),
        D2: D("1009.90"),
        D3: D("1019.80"),
        D4: D("1029.70"),
    }  # tax only subtracts
    v = validate_net(gross, net)
    assert v.passed and v.failures() == [] and v.levels == net
    assert check(v, "net_populated").detail == "first valid net date 2000-01-03, last 2000-01-06"


def test_net_that_starts_later_than_gross_is_fine_but_gaps_and_strays_after_it_are_not():
    gross = {D1: D("1000"), D2: D("1010"), D3: D("1020"), D4: D("1030")}
    late = validate_net(gross, {D3: D("1020.00"), D4: D("1029.70")})  # starts when it starts
    assert late.passed
    holey = validate_net(gross, {D1: D("1000"), D3: D("1019")})  # D2 has gross but no net
    assert (
        not check(holey, "net_contiguous").passed
        and "2000-01-04" in check(holey, "net_contiguous").detail
    )
    stray = validate_net({D1: D("1000")}, {D1: D("1000"), D2: D("999")})
    assert (
        not check(stray, "net_dates_in_gross").passed
        and "2000-01-04" in check(stray, "net_dates_in_gross").detail
    )


def test_net_must_start_at_gross_and_never_gain_on_it():
    gross = {D1: D("1000"), D2: D("1010"), D3: D("1020")}
    wrong_start = validate_net(gross, {D1: D("990"), D2: D("1000"), D3: D("1010")})
    assert not check(wrong_start, "net_starts_at_gross").passed
    gains = validate_net(gross, {D1: D("1000"), D2: D("1000"), D3: D("1020")})  # ratio rises on D3
    assert (
        not check(gains, "net_never_gains_on_gross").passed
        and "2000-01-05" in check(gains, "net_never_gains_on_gross").detail
    )
    rounding = validate_net(
        {D1: D("20000.00"), D2: D("20100.00")}, {D1: D("20000.00"), D2: D("20099.99")}
    )
    assert check(
        rounding, "net_never_gains_on_gross"
    ).passed  # a 2-decimal rounding wobble is tolerated


def test_an_abrupt_change_of_the_net_gross_ratio_is_flagged_for_investigation():
    gross = {D1: D("1000"), D2: D("1000"), D3: D("1000")}
    v = validate_net(gross, {D1: D("1000"), D2: D("1000"), D3: D("990")})  # 1% drop in one day
    assert not check(v, "no_abrupt_net_gross_jump").passed and v.largest_moves[0][1] == D3
    assert float(v.largest_moves[0][0]) == pytest.approx(0.01)


def test_an_empty_net_series_is_reported_and_gaps_are_listed():
    assert not validate_net({D1: D("1")}, {}).passed
    v = validate_net(
        {D1: D("100"), date(2000, 2, 1): D("100")}, {D1: D("100"), date(2000, 2, 1): D("100")}
    )
    assert v.gaps == [(D1, date(2000, 2, 1))]


def _checks():
    from algo.data.benchmark_validate import Check

    return [Check("ok", True, "fine"), Check("bad", False, "2 days ['a', 'b']")]


def test_an_acceptance_is_recorded_but_the_check_still_fails():
    from algo.data.benchmark_validate import check_states, parse_acceptances

    cs = _checks()
    f = parse_acceptances(["bad=ACCEPTED_WITH_EVIDENCE:LABEL:why: colon kept"], cs)
    assert [(x.check, x.state, x.label, x.reason) for x in f] == [
        ("bad", "ACCEPTED_WITH_EVIDENCE", "LABEL", "why: colon kept")
    ]
    assert len(f[0].detail_sha256) == 64
    assert check_states(cs, f) == {"ok": "PASS", "bad": "ACCEPTED_WITH_EVIDENCE"}
    assert check_states(cs, []) == {"ok": "PASS", "bad": "FAIL"}
    assert check_states(cs, parse_acceptances(["bad=UNRESOLVED:L:r"], cs))["bad"] == "UNRESOLVED"


def test_the_acceptance_hash_changes_when_the_flagged_dates_change():
    from algo.data.benchmark_validate import Check, parse_acceptances

    a = parse_acceptances(["bad=UNRESOLVED:L:r"], [Check("bad", False, "1 day ['x']")])
    b = parse_acceptances(["bad=UNRESOLVED:L:r"], [Check("bad", False, "2 days ['x', 'y']")])
    assert a[0].detail_sha256 != b[0].detail_sha256


@pytest.mark.parametrize(
    ("spec", "msg"),
    [
        ("bad", "malformed"),
        ("bad=UNRESOLVED:only-two", "malformed"),
        ("=UNRESOLVED:L:r", "malformed"),
        ("nope=UNRESOLVED:L:r", "no such check"),
        ("bad=MAYBE:L:r", "state must be"),
        ("bad=UNRESOLVED::r", "must not be empty"),
        ("bad=UNRESOLVED:L: ", "must not be empty"),
        ("ok=UNRESOLVED:L:r", "nothing to accept"),
    ],
)
def test_bad_acceptances_are_rejected(spec, msg):
    from algo.data.benchmark_validate import parse_acceptances

    with pytest.raises(ValueError, match=msg):
        parse_acceptances([spec], _checks())


def test_the_same_check_cannot_be_accepted_twice():
    from algo.data.benchmark_validate import parse_acceptances

    with pytest.raises(ValueError, match="twice"):
        parse_acceptances(["bad=UNRESOLVED:L:r", "bad=UNRESOLVED:M:s"], _checks())
