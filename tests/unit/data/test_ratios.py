"""Ratios are hand-calculated from a small made-up company (all figures in crore, stored as rupees)."""

from datetime import UTC, date, datetime
from decimal import Decimal as D

from algo.data.ratios import (
    BY_KEY,
    RATIOS,
    Market,
    Quarter,
    compute,
    known_quarters,
    reading,
    reading_vs_own_past,
)

CR = D(10_000_000)
ENDS = [
    date(2026, 9, 30),
    date(2026, 6, 30),
    date(2026, 3, 31),
    date(2025, 12, 31),
    date(2025, 9, 30),
    date(2025, 6, 30),
    date(2025, 3, 31),
    date(2024, 12, 31),
]
REV = [120, 110, 100, 90, 80, 75, 70, 65]
EXP = [96, 88, 80, 72, 64, 60, 56, 52]
PBT = [24, 22, 20, 18, 16, 15, 14, 13]
PAT = [D("18"), D("16.5"), D("15"), D("13.5"), D("12"), D("11"), D("10"), D("9")]


def cr(n) -> D:
    return D(str(n)) * CR


def company(
    n: int = 8, *, sheet: bool = True, cash: bool = True, bank: bool = False
) -> list[Quarter]:
    out = []
    for i in range(n):
        quarter = {
            "RevenueFromOperations": cr(REV[i]),
            "Expenses": cr(EXP[i]),
            "FinanceCosts": cr(2),
            "DepreciationDepletionAndAmortisationExpense": cr(3),
            "ProfitBeforeTax": cr(PBT[i]),
            "ProfitLossForPeriod": cr(PAT[i]),
            "PaidUpValueOfEquityShareCapital": cr(100),
            "FaceValueOfEquityShareCapital": D(10),
            "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations": PAT[i] / 10,
        }
        instant, ytd = {}, {}
        if sheet and i == 0:
            instant = {
                "Assets": cr(600),
                "Equity": cr(300),
                "BorrowingsNoncurrent": cr(60),
                "BorrowingsCurrent": cr(30),
                "CurrentAssets": cr(250),
                "CurrentLiabilities": cr(100),
                "Inventories": cr(50),
                "TradeReceivablesCurrent": cr(70),
                "CashAndCashEquivalents": cr(30),
                "BankBalanceOtherThanCashAndCashEquivalents": cr(10),
                "CurrentInvestments": cr(20),
            }
        if cash and i == 0:
            ytd = {
                "CashFlowsFromUsedInOperatingActivities": cr(80),
                "ProfitLossForPeriod": cr(D("34.5")),
                "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities": cr(10),
                "PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities": cr(5),
                "RevenueFromOperations": cr(230),
            }
        out.append(
            Quarter(
                ENDS[i],
                datetime(ENDS[i].year, ENDS[i].month, 28, tzinfo=UTC),
                bank,
                quarter,
                ytd,
                instant,
            )
        )
    return out


def val(r, key) -> D:
    v = r[key].value
    assert v is not None, (key, r[key].note)
    return v


def close(a: D, b: float, places: int = 6) -> bool:
    return abs(a - D(str(b))) < D(10) ** -places


def test_profitability_growth_strength_efficiency_and_cash_are_worked_out_by_hand():
    r = compute(company())
    assert close(
        val(r, "operating_margin"), 104 / 420 * 100
    )  # TTM operating profit 29+27+25+23 over TTM sales 420
    assert close(val(r, "net_margin"), 63 / 420 * 100)
    assert close(val(r, "roe"), 21) and close(val(r, "roa"), 10.5)
    assert close(
        val(r, "roce"), 92 / 500 * 100
    )  # (PBT 84 + interest 8) / (assets 600 - current liabilities 100)
    assert (
        close(val(r, "revenue_growth"), 50)
        and close(val(r, "profit_growth"), 50)
        and close(val(r, "eps_growth"), 50)
    )
    assert close(val(r, "revenue_growth_ttm"), (420 / 290 - 1) * 100) and close(
        val(r, "profit_growth_ttm"), 50
    )
    assert close(val(r, "debt_to_equity"), 0.3) and close(val(r, "net_debt_to_ebitda"), 30 / 104)
    assert close(val(r, "interest_coverage"), 11.5)
    assert close(val(r, "current_ratio"), 2.5) and close(val(r, "quick_ratio"), 2.0)
    assert close(val(r, "asset_turnover"), 0.7) and close(val(r, "receivable_days"), 70 / 420 * 365)
    assert (
        close(val(r, "cfo_to_profit"), 80 / 34.5)
        and close(val(r, "free_cash_flow"), 65)
        and close(val(r, "fcf_margin"), 65 / 230 * 100)
    )
    assert r["roe"].as_of == date(2026, 9, 30)
    assert not any(k in r for k in ("pe", "market_cap"))  # no market given


def test_valuation_needs_a_price_and_uses_twelve_month_earnings_and_book_value_per_share():
    r = compute(
        company(), Market(price=D(200), price_date=date(2026, 11, 11), dividend_per_share_12m=D(4))
    )
    assert close(val(r, "market_cap"), 2000)  # 200 x 10 crore shares
    assert close(val(r, "pe"), 200 / 6.3) and close(val(r, "earnings_yield"), 6.3 / 200 * 100)
    assert close(val(r, "pb"), 200 / 30)
    assert close(val(r, "ps"), 2000 / 420) and close(val(r, "ev_ebitda"), 2030 / 104)
    assert close(val(r, "dividend_yield"), 2)
    assert r["pe"].as_of == date(2026, 11, 11)


def test_valuation_is_withheld_after_a_split_without_a_price_or_a_share_count():
    q = company()
    assert compute(q, Market(price=D(200), split_since_results=True))["pe"].note.startswith(
        "a split or bonus"
    )
    assert compute(q, Market(price=None))["pe"].note == "no price"
    assert compute(q, Market(price=D(0)))["market_cap"].value is None
    no_shares = [
        Quarter(
            q[0].period_end,
            q[0].filed_at,
            False,
            {k: v for k, v in q[0].quarter.items() if k != "PaidUpValueOfEquityShareCapital"},
            q[0].ytd,
            q[0].instant,
        ),
        *q[1:],
    ]
    assert compute(no_shares, Market(price=D(200)))["pe"].note == "share count not in the filing"


def test_a_filing_reporting_zero_paid_up_capital_withholds_valuation_instead_of_dividing_by_zero():
    q = company()
    zero = [
        Quarter(
            q[0].period_end,
            q[0].filed_at,
            False,
            {**q[0].quarter, "PaidUpValueOfEquityShareCapital": D(0)},
            q[0].ytd,
            q[0].instant,
        ),
        *q[1:],
    ]
    r = compute(zero, Market(price=D(200)))
    assert (r["pb"].value, r["market_cap"].value) == (None, None)
    assert r["pb"].note == "share count not in the filing"


def test_a_loss_making_company_has_no_pe_but_still_a_book_value():
    q = company()
    loss = [
        Quarter(
            x.period_end,
            x.filed_at,
            x.bank,
            {
                **x.quarter,
                "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations": D("-1"),
            },
            x.ytd,
            x.instant,
        )
        for x in q
    ]
    r = compute(loss, Market(price=D(200)))
    assert (
        r["pe"].value is None
        and "loss-making" in (r["pe"].note or "")
        and r["earnings_yield"].value is None
    )
    assert r["pb"].value is not None


def test_missing_history_gives_reasons_not_numbers():
    r = compute(company(3))
    assert r["operating_margin"].value is None and "four consecutive quarters" in (
        r["operating_margin"].note or ""
    )
    assert r["revenue_growth"].note == "not enough history to compare"
    assert r["revenue_growth_ttm"].value is None
    no_gap = company()
    gap = [no_gap[0], no_gap[1], no_gap[3], *no_gap[4:]]  # March 2026 never filed
    assert compute(gap)["operating_margin"].value is None


def test_no_balance_sheet_or_cash_flow_says_so():
    r = compute(company(sheet=False, cash=False))
    assert (
        r["roe"].note == "no balance sheet in the filings yet" and r["current_ratio"].value is None
    )
    assert (
        r["cfo_to_profit"].note == "no cash flow statement filed yet"
        and r["free_cash_flow"].value is None
    )
    assert (
        compute(company(sheet=False), Market(price=D(200)))["pb"].note
        == "owners' equity is missing, zero or negative"
    )


def test_growth_off_a_zero_or_loss_base_is_not_a_percentage():
    q = company()
    base = [
        x
        if i != 4
        else Quarter(
            x.period_end,
            x.filed_at,
            False,
            {**x.quarter, "RevenueFromOperations": D(0)},
            x.ytd,
            x.instant,
        )
        for i, x in enumerate(q)
    ]
    assert compute(base)["revenue_growth"].note.startswith("a year ago was zero or a loss")


def test_debt_free_loss_making_and_cash_edge_cases():
    q = company()
    debt_free = Quarter(
        q[0].period_end,
        q[0].filed_at,
        False,
        q[0].quarter,
        q[0].ytd,
        {**q[0].instant, "BorrowingsNoncurrent": D(0), "BorrowingsCurrent": D(0)},
    )
    r = compute([debt_free, *q[1:]])
    assert val(r, "debt_to_equity") == 0 and val(r, "net_debt_to_ebitda") < 0  # more cash than debt
    no_interest = [
        Quarter(
            x.period_end, x.filed_at, False, {**x.quarter, "FinanceCosts": D(0)}, x.ytd, x.instant
        )
        for x in q
    ]
    assert compute(no_interest)["interest_coverage"].note == "no interest cost"
    weak = [
        Quarter(
            x.period_end,
            x.filed_at,
            False,
            {**x.quarter, "RevenueFromOperations": cr(10)},
            x.ytd,
            x.instant,
        )
        for x in q
    ]
    assert compute(weak)["net_debt_to_ebitda"].note == "operating profit is zero or negative"
    losing = Quarter(
        q[0].period_end,
        q[0].filed_at,
        False,
        q[0].quarter,
        {**q[0].ytd, "ProfitLossForPeriod": cr(-5)},
        q[0].instant,
    )
    assert compute([losing, *q[1:]])["cfo_to_profit"].note == "profit is zero or a loss"
    no_sales = Quarter(
        q[0].period_end,
        q[0].filed_at,
        False,
        q[0].quarter,
        {k: v for k, v in q[0].ytd.items() if k != "RevenueFromOperations"},
        q[0].instant,
    )
    assert (
        compute([no_sales, *q[1:]])["fcf_margin"].note == "sales for the year so far not reported"
    )


def test_a_bank_gets_bank_ratios_and_none_of_the_company_ones():
    quarters = []
    for i in range(8):
        quarter = {
            "Income": cr(100),
            "InterestExpended": cr(40),
            "OperatingExpenses": cr(30),
            "ProfitLossForThePeriod": cr(10),
            "BasicEarningsPerShareAfterExtraordinaryItems": D("2.5"),
            "PercentageOfGrossNpa": D("1.4"),
            "PercentageOfNpa": D("0.4"),
            "PaidUpValueOfEquityShareCapital": cr(100),
            "FaceValueOfEquityShareCapital": D(10),
        }
        inst = {"Assets": cr(5000), "Equity": cr(400)} if i == 0 else {}
        quarters.append(
            Quarter(
                ENDS[i],
                datetime(ENDS[i].year, ENDS[i].month, 28, tzinfo=UTC),
                True,
                quarter,
                {},
                inst,
            )
        )
    r = compute(quarters, Market(price=D(100)))
    assert close(
        val(r, "cost_to_income"), 120 / 240 * 100
    )  # costs 30x4 over (income 400 - interest paid 160)
    assert close(val(r, "roe"), 40 / 400 * 100) and close(val(r, "roa"), 40 / 5000 * 100)
    assert close(val(r, "gross_npa"), 1.4) and close(val(r, "net_npa"), 0.4)
    assert (
        close(val(r, "pe"), 100 / 10)
        and "debt_to_equity" not in r
        and "ps" not in r
        and "ev_ebitda" not in r
    )
    assert reading(BY_KEY["roe"], val(r, "roe"), bank=True) == "ok"


def test_an_empty_history_has_no_ratios():
    assert compute([]) == {}


def test_a_restatement_is_invisible_until_it_is_filed():
    q = company(1)[0]
    restated = Quarter(
        q.period_end,
        datetime(2026, 11, 20, tzinfo=UTC),
        False,
        {**q.quarter, "ProfitLossForPeriod": cr(99)},
        q.ytd,
        q.instant,
    )
    before = known_quarters([q, restated], datetime(2026, 11, 1, tzinfo=UTC))
    after = known_quarters([q, restated], datetime(2026, 12, 1, tzinfo=UTC))
    assert before[0].quarter["ProfitLossForPeriod"] == cr(18) and after[0].quarter[
        "ProfitLossForPeriod"
    ] == cr(99)
    assert known_quarters([q, restated])[0] is restated
    assert known_quarters([q], datetime(2020, 1, 1, tzinfo=UTC)) == []
    two = company(2)
    assert [x.period_end for x in known_quarters(list(reversed(two)))] == [
        ENDS[0],
        ENDS[1],
    ]  # newest first


def test_the_rule_of_thumb_reads_high_and_low_is_better_ratios_and_stays_silent_without_one():
    roe, de, margin = BY_KEY["roe"], BY_KEY["debt_to_equity"], BY_KEY["operating_margin"]
    assert [reading(roe, D(v), False) for v in (20, 10, 5)] == ["good", "ok", "weak"]
    assert [reading(de, D(v), False) for v in ("0.3", "1", "2")] == ["good", "ok", "weak"]
    assert reading(margin, D(30), False) is None and reading(roe, None, False) is None
    assert reading(de, D(1), True) is None  # a bank has no debt-to-equity rule


def test_every_ratio_is_defined_once_with_a_plain_meaning_and_a_known_group():
    keys = [r.key for r in RATIOS]
    assert len(keys) == len(set(keys))
    assert {r.group for r in RATIOS} == {
        "valuation",
        "profitability",
        "growth",
        "strength",
        "efficiency",
        "cash",
    }
    assert all(
        r.meaning and r.formula and r.unit in {"pct", "x", "days", "inr", "crore"} for r in RATIOS
    )
    assert all(r.better in {"high", "low"} for r in RATIOS if r.rules)


def test_missing_expenses_or_earnings_per_share_leave_the_dependent_ratios_empty_with_a_reason():
    q = company()

    def without(name):
        return [
            Quarter(
                x.period_end,
                x.filed_at,
                False,
                {k: v for k, v in x.quarter.items() if k != name},
                x.ytd,
                x.instant,
            )
            for x in q
        ]

    assert compute(without("Expenses"))["operating_margin"].value is None
    r = compute(
        without("BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations"),
        Market(price=D(200)),
    )
    assert r["pe"].value is None and "earnings per share" in (r["pe"].note or "")


def test_negative_equity_makes_equity_based_ratios_meaningless_instead_of_misleading():
    q = company()
    negative = Quarter(
        q[0].period_end,
        q[0].filed_at,
        False,
        q[0].quarter,
        q[0].ytd,
        {**q[0].instant, "Equity": cr(-300)},
    )
    r = compute([negative, *q[1:]], Market(price=D(200)))
    for key in ("roe", "debt_to_equity", "pb"):
        assert r[key].value is None and "zero or negative" in (r[key].note or ""), key
    assert r["roa"].value is not None  # assets-based ratios still work


def test_a_bank_npa_reported_as_zero_is_treated_as_not_reported():
    quarters = [
        Quarter(
            ENDS[i],
            datetime(ENDS[i].year, ENDS[i].month, 28, tzinfo=UTC),
            True,
            {"Income": cr(100), "PercentageOfGrossNpa": D(0), "PercentageOfNpa": D(0)},
            {},
            {},
        )
        for i in range(4)
    ]
    r = compute(quarters)
    assert r["gross_npa"].value is None and r["net_npa"].note == "not reported"


def test_a_ratio_with_no_fixed_yardstick_is_judged_against_the_companys_own_past():
    pe, margin = BY_KEY["pe"], BY_KEY["net_margin"]
    past = [D(20), D(22), D(24), D(26)]  # median 23
    assert reading_vs_own_past(pe, D(18), past) == "good"  # a lower P/E is the better side
    assert reading_vs_own_past(pe, D(23), past) == "ok"  # within 10% of the median
    assert reading_vs_own_past(pe, D(30), past) == "weak"
    assert (
        reading_vs_own_past(margin, D(30), past) == "good"
        and reading_vs_own_past(margin, D(15), past) == "weak"
    )
    assert (
        reading_vs_own_past(pe, D(18), past[:2]) is None
    )  # too little history to call anything usual
    assert reading_vs_own_past(pe, None, past) is None
    assert reading_vs_own_past(BY_KEY["market_cap"], D(5), past) is None  # size is not good or bad
    assert (
        reading_vs_own_past(pe, D("1.5"), [D(1), D(2), D(3)]) == "good"
    )  # odd count: the middle one is the median


def test_a_catalog_entry_keeps_every_field_exactly_as_defined():
    from algo.data.ratios import RatioDef

    pe = BY_KEY["pe"]
    assert pe == RatioDef(
        "pe",
        "Price to earnings (P/E)",
        "valuation",
        "x",
        "How many years of the last year's profit you pay for. Lower is cheaper, but a low P/E can mean a business in trouble.",
        "price ÷ earnings per share, last 12 months",
        "low",
        "both",
        {},
    )
    roe = BY_KEY["roe"]  # a ratio with thresholds, kept as exact decimals (never floats)
    assert (roe.label, roe.group, roe.unit, roe.better, roe.applies) == (
        "Return on equity (ROE)",
        "profitability",
        "pct",
        "high",
        "both",
    )
    assert roe.formula == "profit to owners, last 12 months ÷ owners' equity"
    assert roe.rules == {"company": (D("15"), D("8")), "bank": (D("14"), D("9"))}
    assert all(isinstance(x, D) for pair in roe.rules.values() for x in pair)
    assert BY_KEY["market_cap"].better is None and BY_KEY["market_cap"].rules == {}
    assert BY_KEY["ps"].applies == "company" and BY_KEY["cost_to_income"].applies == "bank"


# --- valuation: every figure is dated to the price it used, and every gap says why ---
DAY = date(2026, 11, 11)
VALUATION = ("market_cap", "pe", "pb", "earnings_yield", "dividend_yield", "ps", "ev_ebitda")


def with_quarter(q, **changes):
    return [
        Quarter(x.period_end, x.filed_at, x.bank, {**x.quarter, **changes}, x.ytd, x.instant)
        for x in q
    ]


def test_every_valuation_figure_is_dated_to_the_price_it_used():
    r = compute(company(), Market(price=D(200), price_date=DAY, dividend_per_share_12m=D(4)))
    for key in VALUATION:
        assert r[key].as_of == DAY and r[key].note is None, key


def test_a_bank_has_no_price_to_sales_or_ev_ebitda_and_a_company_has_both():
    market = Market(price=D(200), price_date=DAY, dividend_per_share_12m=D(4))
    bank = compute(company(bank=True), market)
    assert [k for k in VALUATION if k in bank] == [
        "market_cap",
        "pe",
        "pb",
        "earnings_yield",
        "dividend_yield",
    ]
    assert [k for k in VALUATION if k in compute(company(), market)] == sorted(
        VALUATION, key=VALUATION.index
    )


def test_without_a_price_or_after_a_split_every_valuation_figure_says_so():
    nothing = compute(company(), Market(price=None))
    for key in VALUATION:
        assert (nothing[key].value, nothing[key].note, nothing[key].as_of) == (
            None,
            "no price",
            None,
        ), key
    split = compute(company(), Market(price=D(200), price_date=DAY, split_since_results=True))
    for key in VALUATION:
        assert split[key].value is None and split[key].note.startswith("a split or bonus since"), (
            key
        )


def test_each_missing_valuation_figure_says_why_and_still_carries_the_price_date():
    market = Market(price=D(200), price_date=DAY)
    short = compute(company(3), market)  # only three quarters: no twelve-month figures
    for key in ("pe", "earnings_yield"):
        assert short[key].note == "needs four consecutive quarters of earnings per share", key
        assert (short[key].value, short[key].as_of) == (None, DAY), key
    assert (short["ps"].value, short["ps"].note, short["ps"].as_of) == (
        None,
        "needs four consecutive quarters",
        DAY,
    )
    assert compute(company(), market)["dividend_yield"].note == "no dividend data"
    assert compute(company(), market)["dividend_yield"].value is None
    assert compute(company(), market)["dividend_yield"].as_of == DAY
    nosheet = compute(company(sheet=False), market)
    for key, why in (
        ("pb", "owners' equity is missing, zero or negative"),
        ("ev_ebitda", "needs a balance sheet and positive operating profit"),
    ):
        assert (nosheet[key].value, nosheet[key].note, nosheet[key].as_of) == (None, why, DAY), key


def test_a_loss_making_year_blanks_pe_and_earnings_yield_with_the_same_reason_and_date():
    loss = with_quarter(
        company(), BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations=D("-1")
    )
    r = compute(loss, Market(price=D(200), price_date=DAY))
    for key in ("pe", "earnings_yield"):
        assert (r[key].value, r[key].note, r[key].as_of) == (
            None,
            "loss-making over the last 12 months: P/E is not meaningful",
            DAY,
        ), key


def test_a_company_whose_operating_profit_is_not_positive_has_no_ev_to_ebitda():
    r = compute(with_quarter(company(), Expenses=cr(500)), Market(price=D(200), price_date=DAY))
    ev = r["ev_ebitda"]
    assert (ev.value, ev.note, ev.as_of) == (
        None,
        "needs a balance sheet and positive operating profit",
        DAY,
    )
