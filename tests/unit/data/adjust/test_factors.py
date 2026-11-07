from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest
from hypothesis import given
from hypothesis import strategies as st

from algo.data.adjust.factors import (
    ActionRecord,
    Adjustment,
    build_adjustments,
    dividend_factor,
    factor_on,
    split_factor,
)

TOL = D("1e-20")  # factors are 28-digit decimals; order of multiplication moves the last digit
KT = datetime(2025, 6, 15, 18, 30, tzinfo=UTC)
EX = date(2025, 6, 16)


def rec(kind, num=None, den=None, amount=None, status="ok", ex=EX, kt=KT):
    return ActionRecord(ex, kind, status, num, den, amount, kt)


def build(*actions, prev=D(100)):
    return build_adjustments(actions, lambda d: prev)


def test_hand_computed_factors():
    assert split_factor(D(2), D(1)) == D("0.5")  # bonus 1:1
    assert split_factor(D(3), D(2)) == D(2) / D(3)  # bonus 1:2 (ITC)
    assert split_factor(D(10), D(2)) == D("0.2")  # 10 -> 2 split
    assert dividend_factor(D(5), D(100)) == D("0.95")


@pytest.mark.parametrize(
    ("a", "p"), [(D(0), D(100)), (D(-1), D(100)), (D(100), D(100)), (D(1), D(0))]
)
def test_bad_dividend_rejected(a, p):
    with pytest.raises(ValueError, match="^dividend must be positive and below previous close$"):
        dividend_factor(a, p)


@pytest.mark.parametrize(("n", "d"), [(D(0), D(1)), (D(1), D(0)), (D(-1), D(1))])
def test_bad_ratio_rejected(n, d):
    with pytest.raises(ValueError, match="^ratio must be positive$"):
        split_factor(n, d)


def test_bonus_and_split_same_day_multiply_bajaj_2025():
    b = build(rec("bonus", D(5), D(1)), rec("split", D(2), D(1)))
    assert [a.factor for a in b.adjustments if a.kind == "split"] == [D("0.2"), D("0.5")]
    assert factor_on(b.adjustments, date(2025, 6, 13)) == D("0.1")


def test_ex_date_bar_is_not_adjusted_prior_bar_is():
    adj = build(rec("split", D(10), D(2))).adjustments
    assert factor_on(adj, EX) == 1 and factor_on(adj, EX - timedelta(days=1)) == D("0.2")
    assert factor_on(adj, EX + timedelta(days=1)) == 1


def test_dividends_only_in_total_return_and_same_day_dividends_are_summed():
    b = build(rec("dividend", amount=D(4)), rec("dividend", amount=D(1)), prev=D(100))
    assert len(b.adjustments) == 1 and b.adjustments[0].factor == D("0.95")
    before = EX - timedelta(days=1)
    assert factor_on(b.adjustments, before) == 1  # split-adjusted series ignores dividends
    assert factor_on(b.adjustments, before, total_return=True) == D("0.95")


def test_review_and_unknown_kinds_are_not_applied_but_reported():
    r1, r2 = rec("rights", D(3), D(19), D(1090), status="review"), rec("demerger", status="review")
    r3 = rec("weird")
    b = build(r1, r2, r3)
    assert b.adjustments == [] and b.unapplied == [r1, r2, r3]


def test_conflicting_ratios_same_day_not_applied():
    a, b2 = rec("bonus", D(11), D(10)), rec("bonus", D(2), D(1))
    b = build(a, b2)
    assert b.adjustments == [] and set(b.unapplied) == {a, b2}


def test_identical_duplicates_apply_once():
    b = build(rec("bonus", D(2), D(1)), rec("bonus", D(2), D(1)))
    assert len(b.adjustments) == 1


def test_point_in_time_hides_actions_not_yet_known():
    adj = build(rec("split", D(2), D(1))).adjustments
    day = date(2025, 6, 10)
    assert factor_on(adj, day, as_of=KT - timedelta(seconds=1)) == 1  # not known yet
    assert factor_on(adj, day, as_of=KT) == D("0.5")  # known exactly at knowledge_time
    assert factor_on(adj, day) == D("0.5")  # as_of=None: full hindsight


def test_knowledge_time_is_latest_of_the_combined_rows():
    late = KT + timedelta(days=1)
    b = build(rec("dividend", amount=D(1)), rec("dividend", amount=D(1), kt=late))
    assert b.adjustments[0].knowledge_time == late


ratio = st.integers(1, 50)


@given(
    ratio, ratio, st.decimals(min_value=D("1"), max_value=D("5000"), places=2), st.integers(1, 1000)
)
def test_split_preserves_position_value_and_price_is_continuous(n, dn, price, qty):
    f = split_factor(D(n), D(dn))
    # holding value unchanged: qty * price (pre) == (qty / f) * (price * f)
    assert D(qty) * price == pytest.approx((D(qty) / f) * (price * f), rel=TOL)
    # market reprices by exactly f at ex-date => adjusted pre-close equals post-close
    post_close = price * f
    adj_pre = price * factor_on([Adjustment(EX, "split", f, KT)], EX - timedelta(days=1))
    assert adj_pre == pytest.approx(post_close, rel=TOL)


@given(st.lists(st.tuples(ratio, ratio), min_size=1, max_size=5))
def test_factor_is_product_in_any_order(ratios):
    adjs = [Adjustment(date(2025, 6, 16 + i), "split", split_factor(D(n), D(d)), KT)
            for i, (n, d) in enumerate(ratios)]  # fmt: skip
    expected = D(1)
    for a in adjs:
        expected *= a.factor
    fwd, rev = factor_on(adjs, date(2025, 6, 1)), factor_on(adjs[::-1], date(2025, 6, 1))
    assert fwd == pytest.approx(expected, rel=TOL) and rev == pytest.approx(expected, rel=TOL)


def test_bad_dividend_goes_to_unapplied_instead_of_crashing_the_whole_build():
    bad = rec("dividend", amount=D(150))  # larger than the previous close: bad data
    good = rec("bonus", D(2), D(1))
    b = build(bad, good, prev=D(100))
    assert [a.kind for a in b.adjustments] == ["split"] and b.unapplied == [bad]


def test_dividend_without_a_previous_close_goes_to_unapplied():
    def no_history(d):
        raise LookupError("no bar before this date")

    div = rec("dividend", amount=D(1))
    b = build_adjustments([div, rec("split", D(2), D(1))], no_history)
    assert [a.kind for a in b.adjustments] == ["split"] and b.unapplied == [div]


# ---- manual-review treatments ------------------------------------------------------------
from algo.data.adjust.factors import demerger_factor, rights_factor  # noqa: E402


def test_demerger_factor_hand_computed():
    # 1 child share per parent share, child worth 280, parent closed at 2800 => parent keeps 90%
    assert demerger_factor(D(1), D(280), D(2800)) == D("0.9")
    assert demerger_factor(D("0.1"), D(500), D(2000)) == D("0.975")  # 1 child per 10 parent


@pytest.mark.parametrize(
    ("ratio", "child", "prev"),
    [
        (D(0), D(100), D(1000)),
        (D(1), D(0), D(1000)),
        (D(1), D(100), D(0)),
        (D(-1), D(100), D(1000)),
    ],
)
def test_demerger_factor_rejects_non_positive_inputs(ratio, child, prev):
    with pytest.raises(ValueError, match="^ratio and prices must be positive$"):
        demerger_factor(ratio, child, prev)


@pytest.mark.parametrize(("ratio", "child"), [(D(1), D(1000)), (D(2), D(600)), (D(1), D(1001))])
def test_demerger_value_must_be_below_the_parent_close(ratio, child):
    with pytest.raises(
        ValueError, match="^demerged value must be below the parent's previous close$"
    ):
        demerger_factor(ratio, child, D(1000))


def test_demerger_with_a_sub_rupee_child_price_is_valid():
    assert demerger_factor(D(1), D("0.5"), D(100)) == D("0.995")


def test_rights_factor_is_theoretical_ex_rights_price_over_cum_price():
    # 1 new share per 15 held at 1257; cum price 1400 => TERP = (15*1400 + 1257)/16
    f = rights_factor(D(1), D(15), D(1257), D(1400))
    assert f == (D(15) * 1400 + 1257) / (D(16) * 1400)
    assert D("0.99") < f < 1


@pytest.mark.parametrize(
    ("new", "held", "sub", "prev"),
    [(D(0), D(15), D(1257), D(1400)), (D(1), D(0), D(1257), D(1400)), (D(1), D(15), D(0), D(1400)),
     (D(1), D(15), D(1257), D(0)), (D(-1), D(15), D(1257), D(1400))],
)  # fmt: skip
def test_rights_factor_rejects_non_positive_inputs(new, held, sub, prev):
    with pytest.raises(ValueError, match="^ratio and prices must be positive$"):
        rights_factor(new, held, sub, prev)


@pytest.mark.parametrize("sub", [D(1400), D(1500)])
def test_rights_issue_not_below_market_is_rejected(sub):
    with pytest.raises(
        ValueError, match="^issue price at or above market: no adjustment, check the inputs$"
    ):
        rights_factor(D(1), D(15), sub, D(1400))


def test_a_sub_rupee_issue_price_and_prices_are_valid():
    assert rights_factor(D(1), D(1), D("0.5"), D(2)) == D("0.625")  # TERP (2 + 0.5) / 2 = 1.25


def resolved(factor, ex=EX, kt=KT):
    return ActionRecord(ex, "resolved", "ok", D(1), D(factor), None, kt)


def test_resolved_action_is_a_price_only_adjustment():
    b = build(resolved("0.9"))
    assert [(a.kind, a.factor) for a in b.adjustments] == [("price", D("0.9"))]
    before = EX - timedelta(days=1)
    assert factor_on(b.adjustments, before) == D("0.9")  # price series
    assert factor_on(b.adjustments, before, total_return=True) == D("0.9")
    assert factor_on(b.adjustments, before, volume=True) == 1  # share count is unchanged


def test_volume_factor_follows_splits_only_even_with_price_and_dividend_adjustments():
    b = build(rec("bonus", D(2), D(1)), resolved("0.9"), rec("dividend", amount=D(5)))
    before = EX - timedelta(days=1)
    assert factor_on(b.adjustments, before, total_return=True, volume=True) == D("0.5")
    assert factor_on(b.adjustments, before) == D("0.45")  # split x resolved


def test_conflicting_resolved_factors_same_day_are_not_applied():
    a, c = resolved("0.9"), resolved("0.8")
    b = build(a, c)
    assert b.adjustments == [] and set(b.unapplied) == {a, c}


# ---- gaps found by mutation testing ------------------------------------------------------------
def test_small_dividends_below_one_rupee_are_valid():
    assert dividend_factor(D("0.5"), D(100)) == D("0.995")
    b = build(rec("dividend", amount=D("0.25")), prev=D(100))
    assert [a.factor for a in b.adjustments] == [D("0.9975")] and b.unapplied == []


def test_dividend_prev_close_is_looked_up_for_the_ex_date_of_that_dividend():
    d1, d2 = date(2025, 6, 16), date(2025, 7, 16)
    closes = {d1: D(100), d2: D(200)}  # a lookup for any other date fails
    recs = [rec("dividend", amount=D(10), ex=d1), rec("dividend", amount=D(10), ex=d2)]
    b = build_adjustments(recs, lambda day: closes[day])
    assert [a.factor for a in b.adjustments] == [D("0.9"), D("0.95")] and b.unapplied == []


def adj(ex, kind, f, kt=KT):
    return Adjustment(ex, kind, D(f), kt)


def test_skipped_adjustments_do_not_hide_later_applicable_ones():
    """Order in the list must not matter: every skip rule must continue, never stop."""
    d = date(2025, 6, 10)
    past = adj(date(2025, 6, 1), "split", "0.5")  # ex <= d : skipped
    later = adj(date(2025, 7, 1), "split", "0.8")
    assert factor_on([past, later], d) == D("0.8")
    div = adj(date(2025, 6, 20), "dividend", "0.9")  # skipped unless total_return
    assert factor_on([div, later], d) == D("0.8")
    assert factor_on([div, later], d, total_return=True) == D("0.72")
    price = adj(date(2025, 6, 20), "price", "0.9")  # skipped for the volume factor
    assert factor_on([price, later], d, volume=True) == D("0.8")
    unknown = adj(date(2025, 6, 20), "split", "0.9", kt=KT + timedelta(days=30))  # not known yet
    assert factor_on([unknown, later], d, as_of=KT) == D("0.8")
    assert factor_on([later, unknown], d, as_of=KT) == D("0.8")


def test_penny_stock_demerger_with_parent_price_below_one_rupee_is_valid():
    assert demerger_factor(D(1), D("0.1"), D("0.8")) == D("0.875")


def test_dividend_record_without_an_amount_is_unapplied_not_a_zero_dividend():
    no_amount = rec("dividend", amount=None)
    b = build(no_amount, rec("bonus", D(2), D(1)))
    assert [a.kind for a in b.adjustments] == ["split"] and b.unapplied == [no_amount]


@pytest.mark.parametrize(("num", "den"), [(None, D(1)), (D(2), None), (None, None)])
def test_malformed_split_record_goes_to_unapplied_instead_of_crashing(num, den):
    bad = rec("bonus", num, den)
    b = build(bad)
    assert b.adjustments == [] and b.unapplied == [bad]


def test_a_review_status_record_is_never_applied_even_if_its_kind_is_known():
    pending = rec("bonus", D(2), D(1), status="review")  # numbers present, but not approved
    b = build(pending)
    assert b.adjustments == [] and b.unapplied == [pending]


def test_a_malformed_record_does_not_stop_later_actions_from_being_processed():
    d1, d2 = date(2025, 6, 16), date(2025, 7, 16)
    bad = ActionRecord(d1, "bonus", "ok", None, None, None, KT)
    good = ActionRecord(d2, "bonus", "ok", D(2), D(1), None, KT)
    b = build(bad, good)
    assert [(a.ex_date, a.factor) for a in b.adjustments] == [(d2, D("0.5"))]
    assert b.unapplied == [bad]
