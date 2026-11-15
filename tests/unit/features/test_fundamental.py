# ruff: noqa: E501
"""Fundamental features: ratios from the filings, as they were KNOWN on each day. Hand-worked values, then the point-in-time rules."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from algo.data import ratios as fr
from algo.features import fundamental
from algo.features._shared import SessionBar


def filed(y, m, d):
    return datetime(y, m, d, 16, 30, tzinfo=UTC)


def quarter(end, filed_at, revenue, pat=None, bank=False):
    figures = {"RevenueFromOperations": D(str(revenue))}
    if pat is not None:
        figures["ProfitLossForPeriod"] = D(str(pat))
    return fr.Quarter(end, filed_at, bank, figures)


# six consecutive reporting quarters, each filed about 40 days after it ended; revenue 100, 105, 110, 120, then 110 (+10% on a year ago) and 126 (+20%)
Q = [
    quarter(date(2023, 3, 31), filed(2023, 5, 10), 100, 10),
    quarter(date(2023, 6, 30), filed(2023, 8, 10), 105, 10),
    quarter(date(2023, 9, 30), filed(2023, 11, 10), 110, 10),
    quarter(date(2023, 12, 31), filed(2024, 2, 10), 120, 10),
    quarter(date(2024, 3, 31), filed(2024, 5, 10), 110, 12),
    quarter(date(2024, 6, 30), filed(2024, 8, 10), 126, 12),
]
DAYS = [
    date(2024, 5, 6) + timedelta(days=i) for i in range(0, 120)
]  # every calendar day: the day-before rule is what is tested, not weekends


def bars(days=DAYS):
    return {
        d: SessionBar(
            d, D(11), D(9), D(10), D(10), D(100), datetime(d.year, d.month, d.day, 13, tzinfo=UTC)
        )
        for d in days
    }


def history(quarters=Q, standalone=None):
    return fundamental.FilingsHistory(
        {"CONSOLIDATED": list(quarters), "STANDALONE": list(standalone or [])}
    )


def run(key, h=None, days=DAYS, b=None):
    return fundamental.ratio(key)(days, b if b is not None else bars(days), h or history())


# ---- hand-worked values ---------------------------------------------------------------------------------------------
def test_revenue_growth_is_the_latest_quarter_against_the_same_quarter_a_year_ago_in_percent():
    r = run("revenue_growth")
    assert r[date(2024, 5, 11)][0] == D("10")  # March 2024 quarter: 110 against 100
    assert r[date(2024, 8, 11)][0] == D("20")  # June 2024 quarter: 126 against 105


def test_net_margin_is_twelve_months_of_profit_over_twelve_months_of_revenue():
    r = run("net_margin")
    assert (
        r[date(2024, 5, 11)][0] == D("9.438202247191")
    )  # the latest four quarters, Jun-23 to Mar-24: profit 10+10+10+12 = 42 over revenue 105+110+120+110 = 445


# ---- point in time ------------------------------------------------------------------------------------------------------
def test_a_filing_counts_from_the_session_after_the_day_it_was_filed_never_the_same_day():
    r = run("revenue_growth")
    assert (
        date(2024, 5, 10) not in r
    )  # filed at 16:30 on the 10th: not known during or at the close of the 10th
    assert min(r) == date(
        2024, 5, 11
    )  # and nothing is known before that: the earlier quarters have no year-ago to compare with
    assert r[date(2024, 5, 11)][1] == filed(
        2024, 5, 10
    )  # available_at is the filing time, not the value day's own bar


def test_a_value_holds_until_the_next_filing_changes_it():
    r = run("revenue_growth")
    assert {r[d][0] for d in DAYS if date(2024, 5, 11) <= d <= date(2024, 8, 10)} == {D("10")}
    assert r[date(2024, 8, 10)][1] == filed(2024, 5, 10) and r[date(2024, 8, 11)][1] == filed(
        2024, 8, 10
    )


def test_a_restatement_replaces_the_figure_only_from_the_day_after_it_is_filed():
    restated = quarter(
        date(2024, 3, 31), filed(2024, 6, 20), 121, 12
    )  # March 2024 revenue restated from 110 to 121
    r = run("revenue_growth", history([*Q, restated]))
    assert r[date(2024, 6, 20)][0] == D(
        "10"
    )  # the original still stands on the day of the restatement
    assert r[date(2024, 6, 21)][0] == D("21")  # 121 against 100
    assert r[date(2024, 6, 21)][1] == filed(2024, 6, 20)


def test_consolidated_figures_are_used_when_they_exist_and_standalone_ones_otherwise():
    stand = [
        quarter(q.period_end, q.filed_at, q.quarter["RevenueFromOperations"] * 2, 5) for q in Q
    ]
    only_standalone = run("revenue_growth", history([], stand))
    both = run("revenue_growth", history(Q, stand))
    assert only_standalone[date(2024, 5, 11)][0] == D("10") and both[date(2024, 5, 11)][0] == D(
        "10"
    )
    mixed = run("revenue_growth", history(Q[:5], [quarter(Q[5].period_end, Q[5].filed_at, 999, 5)]))
    assert (
        mixed[date(2024, 8, 11)][0] == D("10")
    )  # consolidated is preferred while it has known quarters: its June quarter is not there yet, so the March figure stands


# ---- nothing is invented ------------------------------------------------------------------------------------------------
def test_no_filings_a_loss_a_year_ago_or_a_day_without_a_bar_give_no_value():
    assert run("revenue_growth", history([])) == {}
    loss_year_ago = [quarter(date(2023, 3, 31), filed(2023, 5, 10), 0, -5), *Q[1:]]
    assert date(2024, 5, 11) not in run(
        "revenue_growth", history(loss_year_ago)
    )  # growth from zero means nothing
    holey = bars([d for d in DAYS if d != date(2024, 5, 12)])
    assert date(2024, 5, 12) not in run("revenue_growth", b=holey) and date(2024, 5, 13) in run(
        "revenue_growth", b=holey
    )


def test_events_are_worked_out_once_per_company_not_once_per_feature():
    h = history()
    run("revenue_growth", h)
    first = h.events
    run("net_margin", h)
    assert (
        h.events is first
    )  # the same cached list: the heavy ratio engine ran once for this company


def test_only_the_chosen_price_free_ratios_are_features_and_each_names_the_ratio_it_reads():
    assert set(fundamental.KEYS) >= {
        "revenue_growth",
        "profit_growth",
        "roe",
        "net_margin",
        "debt_to_equity",
    }
    assert not {"pe", "pb", "market_cap", "dividend_yield", "eps_growth"} & set(
        fundamental.KEYS
    )  # price- or split-dependent: not here
    known = {d.key for d in fr.RATIOS}
    assert set(fundamental.KEYS) <= known


@pytest.mark.parametrize("key", fundamental.KEYS)
def test_every_chosen_ratio_runs_on_a_sparse_filing_without_error(key):
    r = run(key)
    assert all(isinstance(v, D) for v, _ in r.values())


def test_a_session_before_the_first_filing_has_no_value_and_an_unknown_ratio_is_refused():
    early = [date(2023, 1, 2), date(2023, 1, 3)] + DAYS
    r = run("revenue_growth", days=early)
    assert date(2023, 1, 2) not in r and date(2024, 5, 11) in r  # nothing was filed yet
    with pytest.raises(ValueError, match="pe is not a fundamental feature"):
        fundamental.ratio("pe")


def test_a_history_can_be_cut_at_a_day_keeping_only_what_was_filed_by_then():
    cut = history().truncated(
        date(2024, 5, 10)
    )  # the March 2024 quarter was filed on the 10th: it is in
    assert sorted(f.period_end for f in cut.filings["CONSOLIDATED"]) == [
        date(2023, 3, 31),
        date(2023, 6, 30),
        date(2023, 9, 30),
        date(2023, 12, 31),
        date(2024, 3, 31),
    ]
    earlier = history().truncated(date(2024, 5, 9))
    assert max(f.period_end for f in earlier.filings["CONSOLIDATED"]) == date(2023, 12, 31)
    assert history().truncated(date(2000, 1, 1)).events == []
    # a value worked out from the cut history equals the full history's value for every day up to the cut: nothing later leaked in
    full = run("revenue_growth", history(), days=DAYS)
    short = run(
        "revenue_growth",
        history().truncated(date(2024, 6, 1)),
        days=[d for d in DAYS if d <= date(2024, 6, 1)],
    )
    assert {d: v for d, v in full.items() if d <= date(2024, 6, 1)} == short
