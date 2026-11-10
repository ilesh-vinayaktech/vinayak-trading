from datetime import UTC, date, datetime
from decimal import Decimal as D

from algo.data.fundamentals import QuarterRow, growth_rows, latest_per_period


def q(end, rev, pat=None, filed=None, basis="CONSOLIDATED", sym="AAA", extra=None):
    m = {"revenue": D(rev)}
    if pat is not None:
        m["pat"] = D(pat)
    m.update({k: D(v) for k, v in (extra or {}).items()})
    return QuarterRow(sym, basis, end, filed or datetime(end.year, end.month, 28, tzinfo=UTC), m)


Q = [
    q(date(2023, 12, 31), 100, 10, datetime(2024, 1, 20, tzinfo=UTC)),
    q(date(2024, 3, 31), 110, 12, datetime(2024, 4, 25, tzinfo=UTC)),
    q(date(2024, 6, 30), 120, -5, datetime(2024, 7, 25, tzinfo=UTC)),
    q(date(2024, 9, 30), 130, 20, datetime(2024, 10, 22, tzinfo=UTC)),
    q(date(2024, 12, 31), 150, 30, datetime(2025, 1, 21, tzinfo=UTC)),
]


def by_end(rows):
    return {r.period_end: r for r in rows}


def test_qoq_is_against_the_previous_quarter_and_yoy_against_the_same_quarter_a_year_earlier():
    r = by_end(growth_rows(Q))[date(2024, 12, 31)]
    assert (
        r.metrics["revenue"] == D(150)
        and r.prev_quarter_end == date(2024, 9, 30)
        and r.prev_year_end == date(2023, 12, 31)
    )
    assert r.qoq["revenue"] == (D(150) - D(130)) / D(130) and r.yoy["revenue"] == D("0.5")
    assert r.qoq["pat"] == D("0.5") and r.yoy["pat"] == D(2)  # 10 -> 30


def test_a_figure_is_known_when_the_later_of_its_two_filings_was_made():
    r = by_end(growth_rows(Q))[date(2024, 12, 31)]
    assert r.known_at_qoq == datetime(2025, 1, 21, tzinfo=UTC) and r.known_at_yoy == datetime(
        2025, 1, 21, tzinfo=UTC
    )
    assert r.known_at == datetime(2025, 1, 21, tzinfo=UTC)


def test_growth_off_a_zero_or_negative_base_is_undefined_not_a_misleading_percentage():
    rows = by_end(growth_rows(Q))
    assert "pat" not in rows[date(2024, 9, 30)].qoq  # base was a loss (-5): no percentage
    assert "pat" in rows[date(2024, 9, 30)].base_not_positive_qoq  # and it says why
    assert rows[date(2024, 6, 30)].qoq["pat"] == (D(-5) - D(12)) / D(
        12
    )  # a positive base is fine even when the new value is a loss
    zero = growth_rows([q(date(2024, 3, 31), 0, 1), q(date(2024, 6, 30), 5, 1)])
    r = by_end(zero)[date(2024, 6, 30)]
    assert "revenue" not in r.qoq and "revenue" in r.base_not_positive_qoq


def test_a_missing_comparison_quarter_leaves_growth_empty_never_a_wrong_pairing():
    rows = by_end(growth_rows([Q[0], Q[2]]))  # Mar 2024 is missing
    r = rows[date(2024, 6, 30)]
    assert r.prev_quarter_end is None and r.qoq == {} and r.known_at_qoq is None
    assert (
        r.prev_year_end is None and r.yoy == {} and r.known_at_yoy is None
    )  # Jun 2023 absent as well
    assert r.known_at == r.filed_at
    assert rows[date(2023, 12, 31)].prev_quarter_end is None


def test_only_metrics_present_in_both_quarters_get_growth():
    a = q(date(2024, 3, 31), 100, extra={"eps_basic": "5"})
    b = q(date(2024, 6, 30), 110, 9, extra={"eps_basic": "6"})
    r = by_end(growth_rows([a, b]))[date(2024, 6, 30)]
    assert set(r.qoq) == {"revenue", "eps_basic"} and r.qoq["eps_basic"] == D(
        "0.2"
    )  # pat is new, so no growth


def test_the_ebitda_proxy_is_revenue_less_operating_costs_and_needs_all_its_lines():
    a = q(
        date(2024, 3, 31),
        1000,
        extra={"expenses": "800", "finance_costs": "50", "depreciation": "100"},
    )
    b = q(
        date(2024, 6, 30),
        1100,
        extra={"expenses": "850", "finance_costs": "50", "depreciation": "100"},
    )
    rows = by_end(growth_rows([a, b]))
    assert rows[date(2024, 3, 31)].metrics["ebitda_proxy"] == D(1000) - (D(800) - D(50) - D(100))
    assert (
        rows[date(2024, 6, 30)].qoq["ebitda_proxy"] == (D(500) - D(350)) / D(350)
        if False
        else rows[date(2024, 6, 30)].qoq["ebitda_proxy"]
        == (D(1100) - (D(850) - D(50) - D(100)) - D(350)) / D(350)
    )
    assert (
        "ebitda_proxy"
        not in by_end(growth_rows([q(date(2024, 3, 31), 1000)]))[date(2024, 3, 31)].metrics
    )


def test_the_latest_filing_known_as_of_a_date_wins_so_restatements_are_point_in_time():
    first = q(date(2024, 12, 31), 150, 30, datetime(2025, 1, 21, tzinfo=UTC))
    restated = q(date(2024, 12, 31), 140, 25, datetime(2025, 5, 2, tzinfo=UTC))
    rows = [first, restated]
    assert latest_per_period(list(reversed(rows)), None)[0].metrics["revenue"] == D(
        140
    )  # order of arrival does not matter
    assert latest_per_period(rows, datetime(2025, 3, 1, tzinfo=UTC))[0].metrics["revenue"] == D(150)
    assert latest_per_period(rows, datetime(2025, 6, 1, tzinfo=UTC))[0].metrics["revenue"] == D(140)
    assert latest_per_period(rows, None)[0].metrics["revenue"] == D(140)
    assert latest_per_period(rows, datetime(2025, 1, 1, tzinfo=UTC)) == []  # nothing was public yet


def test_standalone_and_consolidated_series_never_mix_and_companies_are_separate():
    rows = [
        q(date(2024, 3, 31), 100, basis="STANDALONE"), q(date(2024, 6, 30), 200, basis="CONSOLIDATED"),
        q(date(2024, 3, 31), 50, sym="BBB"), q(date(2024, 6, 30), 60, sym="BBB"),
    ]  # fmt: skip
    out = {(r.symbol, r.basis, r.period_end): r for r in growth_rows(rows)}
    assert (
        out[("AAA", "CONSOLIDATED", date(2024, 6, 30))].qoq == {}
    )  # its March is standalone: not a pairing
    assert out[("BBB", "CONSOLIDATED", date(2024, 6, 30))].qoq["revenue"] == D("0.2")


def test_as_of_applies_to_growth_so_a_quarter_not_yet_filed_does_not_exist():
    asof = datetime(2024, 11, 1, tzinfo=UTC)
    out = growth_rows(Q, asof)
    assert max(r.period_end for r in out) == date(2024, 9, 30)
    assert by_end(out)[date(2024, 9, 30)].known_at == datetime(2024, 10, 22, tzinfo=UTC)
