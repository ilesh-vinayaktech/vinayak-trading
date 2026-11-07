import math
from datetime import date
from decimal import Decimal as D

import pytest

from algo.data.benchmark_compare import compare, correlation, daily_returns, percentile


def s(*pairs):
    return {date(2024, 1, d): D(str(v)) for d, v in pairs}


A = s((1, 100), (2, 101), (3, 101), (4, 103.02), (5, 104), (6, 103))  # +1%, 0%, +2%
B = s((1, 200), (2, 204), (3, 206.04), (4, 208.08), (5, 209), (6, 212))  # +2%, +1%, +1%


def test_returns_come_from_the_series_own_consecutive_observations():
    r = daily_returns(s((1, 100), (3, 110)))  # day 2 missing: one 10% return over 1 -> 3
    assert r == {date(2024, 1, 3): (date(2024, 1, 1), pytest.approx(0.10))}


def test_compare_reports_every_metric():
    c = compare(A, B, top=2)
    assert (c.overlap, c.compared) == ((date(2024, 1, 1), date(2024, 1, 6)), 5)
    assert not c.only_a and not c.only_b and not c.misaligned
    assert c.max_abs_diff == pytest.approx(0.02397, abs=1e-5) and c.p99_abs_diff == c.max_abs_diff
    assert len(c.largest) == 2 and [d.day.day for d in c.largest] == [6, 4]  # worst first
    w = c.largest[0]
    assert w.diff == pytest.approx(w.ret_a - w.ret_b) and abs(w.diff) == c.max_abs_diff
    assert c.cumulative_a == pytest.approx(0.03) and c.cumulative_b == pytest.approx(0.06)
    assert -1 <= c.correlation <= 1


def test_a_session_missing_on_one_side_is_not_bridged():
    b = {d: v for d, v in B.items() if d != date(2024, 1, 3)}
    c = compare(A, b)
    assert c.only_a == (date(2024, 1, 3),) and c.only_b == ()
    assert c.misaligned == (date(2024, 1, 4),)  # B's day-4 return spans 2 -> 4, A's spans 3 -> 4
    assert c.compared == 3  # days 2, 5, 6 are comparable


def test_missing_on_the_other_side_is_reported_too():
    a = {d: v for d, v in A.items() if d != date(2024, 1, 2)}
    assert compare(a, B).only_b == (date(2024, 1, 2),)


def test_series_must_overlap_and_have_enough_common_dates():
    with pytest.raises(ValueError, match="do not overlap"):
        compare(s((1, 1), (2, 2)), s((3, 1), (4, 2)))
    with pytest.raises(ValueError, match="fewer than two"):
        compare(s((1, 1), (2, 2)), s((1, 1), (2, 3)))


def test_percentile_and_correlation():
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.0
    assert percentile([5.0], 0.99) == 5.0
    assert percentile([1.0, 2.0], 0.0) == 1.0
    assert correlation([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    assert correlation([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert math.isnan(correlation([1, 1, 1], [1, 2, 3]))


def test_wedge_is_the_dividend_part_and_flags_a_price_that_outruns_the_tri():
    from algo.data.benchmark_compare import wedge

    price = s((1, 1000), (2, 1010), (3, 1000), (4, 1010), (5, 1020), (6, 1030))
    tri = s((1, 1000), (2, 1010), (3, 1000), (4, 1020.1), (5, 1030.2), (6, 1030))
    w = wedge(price, tri, top=2)
    assert w.compared == 5 and not w.only_price and not w.only_tri and not w.misaligned
    assert w.wedge_days == 1  # day 4 only: a dividend reinvested
    assert [d for d, _ in w.price_beats_tri] == [date(2024, 1, 6)]  # price +0.98% vs TRI 0.0%
    assert w.top5pct_share == pytest.approx(1.0)  # the whole positive wedge is on one day
    assert w.by_year[0][0] == 2024 and len(w.largest) == 2
    assert w.largest[0].day in (date(2024, 1, 4), date(2024, 1, 6))


def test_wedge_reports_missing_and_misaligned_sessions_and_handles_no_wedge():
    from algo.data.benchmark_compare import wedge

    price = s((1, 100), (2, 101), (3, 102), (4, 103), (5, 104))
    tri = {d: v for d, v in price.items() if d != date(2024, 1, 3)}
    w = wedge(price, tri)
    assert w.only_price == (date(2024, 1, 3),) and w.misaligned == (date(2024, 1, 4),)
    assert w.wedge_days == 0 and w.top5pct_share == 0.0 and not w.price_beats_tri


A_EDGE = s((2, 100), (3, 101), (4, 102), (5, 103), (6, 104))
B_EDGE = s((1, 100), (3, 101), (4, 102.5), (5, 103.5), (7, 105))


def test_dates_on_the_edge_of_the_overlap_are_reported_for_either_side():
    c = compare(A_EDGE, B_EDGE)
    assert (c.overlap, c.only_a, c.only_b) == (
        (date(2024, 1, 2), date(2024, 1, 6)),
        (date(2024, 1, 2), date(2024, 1, 6)),
        (),
    )
    r = compare(B_EDGE, A_EDGE)
    assert r.only_b == (date(2024, 1, 2), date(2024, 1, 6)) and r.only_a == ()


def test_wedge_edges_and_error_messages():
    from algo.data.benchmark_compare import wedge

    w = wedge(A_EDGE, B_EDGE)
    assert w.only_price == (date(2024, 1, 2), date(2024, 1, 6)) and w.only_tri == ()
    assert wedge(B_EDGE, A_EDGE).only_tri == (date(2024, 1, 2), date(2024, 1, 6))
    with pytest.raises(ValueError, match="^the series do not overlap$"):
        compare(s((1, 1), (2, 2)), s((2, 1), (3, 2)))  # they share one date only
    with pytest.raises(ValueError, match="^fewer than two comparable dates$"):
        compare(s((1, 1), (2, 2), (3, 3)), s((1, 1), (2, 3), (4, 3)))
    two = compare(s((1, 100), (2, 101), (3, 103)), s((1, 100), (2, 102), (3, 103)))
    assert two.compared == 2  # exactly two comparable dates is enough


def test_wedge_concentration_uses_the_largest_five_percent_of_days_in_order():
    from algo.data.benchmark_compare import wedge

    n = 100
    price = {
        date(2024, 1, 1) + __import__("datetime").timedelta(days=i): D(1000) for i in range(n + 1)
    }
    tri, level = {}, D(1000)
    for i, d in enumerate(sorted(price)):
        level = level * (1 + D(i) / D(1000)) if i else level
        tri[d] = level
    w = wedge(price, tri)
    assert w.wedge_days == 100
    top5 = sum(i / 1000 for i in range(100, 95, -1))
    total = sum(i / 1000 for i in range(1, 101))
    assert w.top5pct_share == pytest.approx(top5 / total, rel=1e-6)
    assert w.largest[0].day == max(price)
