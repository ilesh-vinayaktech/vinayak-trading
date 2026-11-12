# ruff: noqa: E501  (the ratio table and one-line formulas are kept readable)
"""Fundamental ratios from filed results, point-in-time safe and pure (no clock, no database, no network).

A ratio is computed only from filings known at the time (`known_quarters` drops anything filed later, and a restated quarter
replaces the earlier filing only once the restatement is filed), so a backtest that asks "what were the ratios on that day"
cannot see the future. Money is Decimal. A ratio that cannot be worked out is returned with value None and the reason, never a
guess and never zero. Trailing-twelve-month (TTM) figures need four consecutive reported quarters. Balance-sheet ratios use the
latest balance sheet (filed half-yearly) and the TTM ending on that balance-sheet date, so numerator and denominator cover the
same period.

`RATIOS` is the one definition of every ratio (label, unit, formula in words, rule of thumb) used by the API, the UI and, later,
strategies."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

D = Decimal
ZERO, HUNDRED = D(0), D(100)
Figures = Mapping[str, Decimal]


@dataclass(frozen=True)
class Quarter:
    period_end: date
    filed_at: datetime
    bank: bool
    quarter: Figures
    ytd: Figures = field(default_factory=dict)
    instant: Figures = field(default_factory=dict)


@dataclass(frozen=True)
class Market:
    """What the market adds: the latest unadjusted close, dividends declared in the last 12 months, and whether a split or
    bonus happened after the latest results (then per-share results and the price are on different bases)."""

    price: Decimal | None
    price_date: date | None = None
    dividend_per_share_12m: Decimal | None = None
    split_since_results: bool = False


@dataclass(frozen=True)
class RatioValue:
    value: Decimal | None
    note: str | None = None  # why there is no value, or a caveat
    as_of: date | None = None  # the quarter / balance-sheet date the figure belongs to


@dataclass(frozen=True)
class RatioDef:
    key: str
    label: str
    group: str  # valuation | profitability | growth | strength | efficiency | cash
    unit: str  # pct | x | days | inr | crore
    meaning: str
    formula: str
    better: str | None = None  # "high" | "low" | None (no judgement: depends on the business)
    applies: str = "both"  # company | bank | both
    # rule of thumb per kind of company: (good if at least/at most this, weak if worse than this). Not advice.
    rules: Mapping[str, tuple[Decimal, Decimal]] = field(default_factory=dict)


def _r(
    key: str,
    label: str,
    group: str,
    unit: str,
    meaning: str,
    formula: str,
    better: str | None = None,
    applies: str = "both",
    **rules: tuple[float, float],
) -> RatioDef:
    return RatioDef(
        key,
        label,
        group,
        unit,
        meaning,
        formula,
        better,
        applies,
        {k: (D(str(v[0])), D(str(v[1]))) for k, v in rules.items()},
    )


RATIOS: tuple[RatioDef, ...] = (
    _r(
        "market_cap",
        "Market value",
        "valuation",
        "crore",
        "What the whole company is worth on the stock market today.",
        "price × shares in issue",
    ),
    _r(
        "pe",
        "Price to earnings (P/E)",
        "valuation",
        "x",
        "How many years of the last year's profit you pay for. Lower is cheaper, but a low P/E can mean a business in trouble.",
        "price ÷ earnings per share, last 12 months",
        better="low",
    ),
    _r(
        "pb",
        "Price to book (P/B)",
        "valuation",
        "x",
        "Price against what the company's owners' money (assets less debts) is worth on the books.",
        "price ÷ book value per share",
        better="low",
    ),
    _r(
        "ps",
        "Price to sales",
        "valuation",
        "x",
        "Price against sales, useful when profits are small or negative.",
        "market value ÷ sales, last 12 months",
        applies="company",
        better="low",
    ),
    _r(
        "ev_ebitda",
        "EV to operating profit",
        "valuation",
        "x",
        "What a buyer would pay for the whole business, debt included, against its operating profit.",
        "(market value + debt − cash) ÷ operating profit, last 12 months",
        applies="company",
        better="low",
    ),
    _r(
        "earnings_yield",
        "Earnings yield",
        "valuation",
        "pct",
        "Profit per ₹100 you pay for the share. The opposite of P/E.",
        "earnings per share ÷ price",
        better="high",
    ),
    _r(
        "dividend_yield",
        "Dividend yield",
        "valuation",
        "pct",
        "Cash dividend per ₹100 you pay, over the last 12 months.",
        "dividends declared in 12 months ÷ price",
        better="high",
    ),
    _r(
        "roe",
        "Return on equity (ROE)",
        "profitability",
        "pct",
        "Profit made on the owners' money in the business. Higher is better.",
        "profit to owners, last 12 months ÷ owners' equity",
        "high",
        company=(15, 8),
        bank=(14, 9),
    ),
    _r(
        "roa",
        "Return on assets (ROA)",
        "profitability",
        "pct",
        "Profit made from everything the company owns.",
        "profit, last 12 months ÷ total assets",
        "high",
        company=(8, 3),
        bank=(1.2, 0.6),
    ),
    _r(
        "roce",
        "Return on capital employed (ROCE)",
        "profitability",
        "pct",
        "Operating return on the money tied up in the business, before interest and tax.",
        "(profit before tax + interest) ÷ (total assets − current liabilities)",
        "high",
        "company",
        company=(15, 8),
    ),
    _r(
        "operating_margin",
        "Operating margin",
        "profitability",
        "pct",
        "Operating profit kept from every ₹100 of sales, before interest, depreciation and tax. Compare within the same industry.",
        "operating profit ÷ sales, last 12 months",
        applies="company",
        better="high",
    ),
    _r(
        "net_margin",
        "Net profit margin",
        "profitability",
        "pct",
        "Profit kept from every ₹100 of sales after all costs and tax.",
        "net profit ÷ sales, last 12 months",
        better="high",
    ),
    _r(
        "cost_to_income",
        "Cost to income",
        "profitability",
        "pct",
        "Running costs against what the bank earns before bad-loan provisions. Lower is better.",
        "operating expenses ÷ (net interest income + other income), last 12 months",
        "low",
        "bank",
        bank=(45, 60),
    ),
    _r(
        "revenue_growth",
        "Sales growth (quarter, YoY)",
        "growth",
        "pct",
        "How much sales grew against the same quarter last year.",
        "latest quarter ÷ same quarter a year earlier − 1",
        "high",
        company=(10, 0),
        bank=(10, 0),
    ),
    _r(
        "profit_growth",
        "Profit growth (quarter, YoY)",
        "growth",
        "pct",
        "How much profit grew against the same quarter last year.",
        "latest quarter ÷ same quarter a year earlier − 1",
        "high",
        company=(10, 0),
        bank=(10, 0),
    ),
    _r(
        "eps_growth",
        "EPS growth (quarter, YoY)",
        "growth",
        "pct",
        "Growth in profit for each share.",
        "latest quarter ÷ same quarter a year earlier − 1",
        "high",
        company=(10, 0),
        bank=(10, 0),
    ),
    _r(
        "revenue_growth_ttm",
        "Sales growth (12 months)",
        "growth",
        "pct",
        "Sales of the last 12 months against the 12 months before: smooths out a single odd quarter.",
        "last 12 months ÷ the 12 months before − 1",
        "high",
        company=(10, 0),
        bank=(10, 0),
    ),
    _r(
        "profit_growth_ttm",
        "Profit growth (12 months)",
        "growth",
        "pct",
        "Profit of the last 12 months against the 12 months before.",
        "last 12 months ÷ the 12 months before − 1",
        "high",
        company=(10, 0),
        bank=(10, 0),
    ),
    _r(
        "debt_to_equity",
        "Debt to equity",
        "strength",
        "x",
        "Rupees borrowed for every ₹1 of owners' money. Lower is safer.",
        "borrowings ÷ owners' equity",
        "low",
        "company",
        company=(0.5, 1.5),
    ),
    _r(
        "net_debt_to_ebitda",
        "Net debt to operating profit",
        "strength",
        "x",
        "Years of operating profit needed to repay debt after using cash. Lower is safer; negative means more cash than debt.",
        "(borrowings − cash and investments) ÷ operating profit, last 12 months",
        "low",
        "company",
        company=(1, 3),
    ),
    _r(
        "interest_coverage",
        "Interest cover",
        "strength",
        "x",
        "How many times profit before interest and tax covers the interest bill. Below 2 is thin.",
        "(profit before tax + interest) ÷ interest, last 12 months",
        "high",
        "company",
        company=(5, 2),
    ),
    _r(
        "current_ratio",
        "Current ratio",
        "strength",
        "x",
        "Short-term assets against bills due within a year. Above 1.5 is comfortable.",
        "current assets ÷ current liabilities",
        "high",
        "company",
        company=(1.5, 1),
    ),
    _r(
        "quick_ratio",
        "Quick ratio",
        "strength",
        "x",
        "Like the current ratio, but without stock that may be hard to sell fast.",
        "(current assets − inventories) ÷ current liabilities",
        "high",
        "company",
        company=(1, 0.7),
    ),
    _r(
        "gross_npa",
        "Gross bad loans",
        "strength",
        "pct",
        "Share of loans the bank is not being repaid on. Lower is better.",
        "reported gross NPA %, latest quarter",
        "low",
        "bank",
        bank=(2, 5),
    ),
    _r(
        "net_npa",
        "Net bad loans",
        "strength",
        "pct",
        "Bad loans after setting money aside for them. Lower is better.",
        "reported net NPA %, latest quarter",
        "low",
        "bank",
        bank=(0.7, 2),
    ),
    _r(
        "asset_turnover",
        "Asset turnover",
        "efficiency",
        "x",
        "Sales produced for every ₹1 of assets. Compare within the same industry.",
        "sales, last 12 months ÷ total assets",
        applies="company",
        better="high",
    ),
    _r(
        "receivable_days",
        "Days of sales owed by customers",
        "efficiency",
        "days",
        "How long customers take to pay. Lower and steady is better.",
        "trade receivables ÷ sales, last 12 months × 365",
        "low",
        "company",
    ),
    _r(
        "cfo_to_profit",
        "Cash from operations vs profit",
        "cash",
        "x",
        "Whether profit is turning into cash. Near or above 1 is healthy.",
        "cash from operations ÷ net profit, year to date",
        "high",
        "company",
        company=(0.8, 0.5),
    ),
    _r(
        "free_cash_flow",
        "Free cash flow (year so far)",
        "cash",
        "crore",
        "Cash left after running the business and buying equipment.",
        "cash from operations − spending on plant, equipment and intangibles",
        "high",
        "company",
        company=(1, 0),
    ),
    _r(
        "fcf_margin",
        "Free cash flow margin",
        "cash",
        "pct",
        "Free cash flow per ₹100 of sales.",
        "free cash flow ÷ sales, year to date",
        "high",
        "company",
        company=(8, 0),
    ),
)
BY_KEY = {r.key: r for r in RATIOS}


def reading(defn: RatioDef, value: Decimal | None, bank: bool) -> str | None:
    """ "good" | "ok" | "weak" by the rule of thumb for this kind of company, None if no rule or no value."""
    rule = defn.rules.get("bank" if bank else "company")
    if value is None or rule is None or defn.better is None:
        return None
    good, weak = rule
    if defn.better == "high":
        return "good" if value >= good else "weak" if value < weak else "ok"
    return "good" if value <= good else "weak" if value > weak else "ok"


def reading_vs_own_past(
    defn: RatioDef, current: Decimal | None, past: Sequence[Decimal]
) -> str | None:
    """For ratios with no fixed yardstick (valuation, margins, turnover): is it better, usual or worse than this company's own
    recent past? "good" / "ok" / "weak" = better than usual / in its usual range / worse than usual, where better follows
    `defn.better` (a lower P/E is the better side). Needs at least three earlier quarters; "usual" is within 10% of the median."""
    if current is None or defn.better is None or len(past) < 3:
        return None
    ordered = sorted(past)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    band = abs(median) * D("0.1")
    if abs(current - median) <= band:
        return "ok"
    higher = current > median
    return "good" if higher == (defn.better == "high") else "weak"


# --- known quarters ---------------------------------------------------------------------------------------------------


def known_quarters(filings: Sequence[Quarter], as_of: datetime | None = None) -> list[Quarter]:
    """The latest filing per quarter known at `as_of` (all of them if None), newest quarter first. A restatement filed after
    `as_of` is invisible."""
    best: dict[date, Quarter] = {}
    for f in filings:
        if as_of is not None and f.filed_at > as_of:
            continue
        cur = best.get(f.period_end)
        if cur is None or f.filed_at > cur.filed_at:
            best[f.period_end] = f
    return sorted(best.values(), key=lambda q: q.period_end, reverse=True)


# --- figures ------------------------------------------------------------------------------------------------------------


def _pick(f: Figures, *names: str) -> Decimal | None:
    return next((f[n] for n in names if n in f), None)


def _revenue(q: Quarter) -> Decimal | None:
    return (
        _pick(q.quarter, "Income")
        if q.bank
        else _pick(q.quarter, "RevenueFromOperations", "Income")
    )


def _pat(f: Figures) -> Decimal | None:
    return _pick(f, "ProfitLossForPeriod", "ProfitLossForThePeriod")


def _pat_owners(q: Quarter) -> Decimal | None:
    return _pick(q.quarter, "ProfitOrLossAttributableToOwnersOfParent") or _pat(q.quarter)


def _pbt(q: Quarter) -> Decimal | None:
    return _pick(q.quarter, "ProfitBeforeTax", "ProfitLossFromOrdinaryActivitiesBeforeTax")


def _operating(q: Quarter) -> Decimal | None:
    rev, exp = _revenue(q), _pick(q.quarter, "Expenses")
    if rev is None or exp is None:
        return None
    return rev - (
        exp
        - (_pick(q.quarter, "FinanceCosts") or ZERO)
        - (_pick(q.quarter, "DepreciationDepletionAndAmortisationExpense") or ZERO)
    )


def _ebit(q: Quarter) -> Decimal | None:
    pbt = _pbt(q)
    return None if pbt is None else pbt + (_pick(q.quarter, "FinanceCosts") or ZERO)


def _eps(q: Quarter) -> Decimal | None:
    return _pick(
        q.quarter,
        "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
        "BasicEarningsPerShareAfterExtraordinaryItems",
    )


def _equity(q: Quarter) -> Decimal | None:
    return _pick(q.instant, "EquityAttributableToOwnersOfParent", "Equity")


def _debt(q: Quarter) -> Decimal | None:
    a, b = _pick(q.instant, "BorrowingsNoncurrent"), _pick(q.instant, "BorrowingsCurrent")
    return None if a is None and b is None else (a or ZERO) + (b or ZERO)


def _liquid(q: Quarter) -> Decimal:
    return sum(
        (
            _pick(q.instant, n) or ZERO
            for n in (
                "CashAndCashEquivalents",
                "BankBalanceOtherThanCashAndCashEquivalents",
                "CurrentInvestments",
            )
        ),
        ZERO,
    )


def _chain(qs: Sequence[Quarter], i: int, n: int = 4) -> list[Quarter] | None:
    """Quarters qs[i..i+n-1] if they are consecutive reporting quarters (80..100 days apart), else None."""
    if i < 0 or i + n > len(qs):
        return None
    got = list(qs[i : i + n])
    return (
        got
        if all(
            80 <= (a.period_end - b.period_end).days <= 100
            for a, b in zip(got, got[1:], strict=False)
        )
        else None
    )


def _ttm(qs: Sequence[Quarter], i: int, get: Callable[[Quarter], Decimal | None]) -> Decimal | None:
    ch = _chain(qs, i)
    if ch is None:
        return None
    vals = [get(q) for q in ch]
    return None if any(v is None for v in vals) else sum((v for v in vals if v is not None), ZERO)


def _year_ago(qs: Sequence[Quarter], i: int) -> int | None:
    for j in range(i + 1, len(qs)):
        if abs((qs[i].period_end - qs[j].period_end).days - 365) <= 10:
            return j
    return None


def _div(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None or not b else a / b


def _pct(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    x = _div(a, b)
    return None if x is None else x * HUNDRED


def _growth(cur: Decimal | None, prev: Decimal | None) -> RatioValue:
    if cur is None or prev is None:
        return RatioValue(None, "not enough history to compare")
    if prev <= 0:
        return RatioValue(None, "a year ago was zero or a loss, so a growth rate means nothing")
    return RatioValue((cur - prev) / prev * HUNDRED)


# --- the computation ----------------------------------------------------------------------------------------------------


def compute(quarters: Sequence[Quarter], market: Market | None = None) -> dict[str, RatioValue]:
    """Every ratio that applies to this company, from `quarters` (newest first, as `known_quarters` returns them)."""
    if not quarters:
        return {}
    q0 = quarters[0]
    bank = q0.bank
    out: dict[str, RatioValue] = {}
    b = next(
        (
            i
            for i, q in enumerate(quarters)
            if _equity(q) is not None or _pick(q.instant, "Assets") is not None
        ),
        None,
    )
    qb = quarters[b] if b is not None else None
    sheet = qb.period_end if qb else None
    no_sheet = "no balance sheet in the filings yet"

    def put(
        key: str, value: Decimal | None, note: str | None = None, as_of: date | None = None
    ) -> None:
        out[key] = RatioValue(value, None if value is not None else note, as_of)

    def on_sheet(key: str, fn: Callable[[Quarter, int], tuple[Decimal | None, str | None]]) -> None:
        if qb is None or b is None:
            put(key, None, no_sheet)
        else:
            v, why = fn(qb, b)
            put(
                key,
                v,
                why or (None if v is not None else "a figure it needs is not in the filing"),
                sheet,
            )

    # growth, on the latest quarter and on the last 12 months
    j = _year_ago(quarters, 0)
    for key, get in (
        ("revenue_growth", _revenue),
        ("profit_growth", _pat_owners),
        ("eps_growth", _eps),
    ):
        g = _growth(get(q0), get(quarters[j]) if j is not None else None)
        out[key] = RatioValue(g.value, g.note, q0.period_end)
    for key, get in (("revenue_growth_ttm", _revenue), ("profit_growth_ttm", _pat_owners)):
        prev_i = _year_ago(quarters, 0)
        g = _growth(_ttm(quarters, 0, get), None if prev_i is None else _ttm(quarters, prev_i, get))
        out[key] = RatioValue(g.value, g.note, q0.period_end)

    # profitability
    rev_ttm = _ttm(quarters, 0, _revenue)
    put(
        "net_margin",
        _pct(_ttm(quarters, 0, _pat_owners), rev_ttm),
        "needs four consecutive quarters",
        q0.period_end,
    )
    on_sheet("roe", lambda q, i: _on_equity(q, _pct(_ttm(quarters, i, _pat_owners), _equity(q))))
    on_sheet(
        "roa", lambda q, i: (_pct(_ttm(quarters, i, _pat_owners), _pick(q.instant, "Assets")), None)
    )
    if bank:
        income = _ttm(quarters, 0, _revenue)
        paid = _ttm(quarters, 0, lambda q: _pick(q.quarter, "InterestExpended"))
        opex = _ttm(quarters, 0, lambda q: _pick(q.quarter, "OperatingExpenses"))
        put(
            "cost_to_income",
            _pct(opex, None if income is None or paid is None else income - paid),
            "needs four consecutive quarters",
            q0.period_end,
        )
        put("gross_npa", _npa(q0, "PercentageOfGrossNpa"), "not reported", q0.period_end)
        put("net_npa", _npa(q0, "PercentageOfNpa"), "not reported", q0.period_end)
    else:
        op_ttm = _ttm(quarters, 0, _operating)
        put(
            "operating_margin",
            _pct(op_ttm, rev_ttm),
            "needs four consecutive quarters",
            q0.period_end,
        )
        on_sheet(
            "roce",
            lambda q, i: (
                _pct(
                    _ttm(quarters, i, _ebit),
                    None
                    if (a := _pick(q.instant, "Assets")) is None
                    or (c := _pick(q.instant, "CurrentLiabilities")) is None
                    else a - c,
                ),
                None,
            ),
        )
        on_sheet("debt_to_equity", lambda q, i: _on_equity(q, _div(_debt(q), _equity(q))))
        on_sheet("net_debt_to_ebitda", lambda q, i: _net_debt_cover(quarters, q, i))
        on_sheet("interest_coverage", lambda q, i: _interest_cover(quarters, i))
        on_sheet(
            "current_ratio",
            lambda q, i: (
                _div(_pick(q.instant, "CurrentAssets"), _pick(q.instant, "CurrentLiabilities")),
                None,
            ),
        )
        on_sheet(
            "quick_ratio",
            lambda q, i: (
                _div(
                    None
                    if (ca := _pick(q.instant, "CurrentAssets")) is None
                    else ca - (_pick(q.instant, "Inventories") or ZERO),
                    _pick(q.instant, "CurrentLiabilities"),
                ),
                None,
            ),
        )
        on_sheet(
            "asset_turnover",
            lambda q, i: (_div(_ttm(quarters, i, _revenue), _pick(q.instant, "Assets")), None),
        )
        on_sheet(
            "receivable_days",
            lambda q, i: (
                None
                if (
                    r := _div(
                        _pick(q.instant, "TradeReceivablesCurrent"), _ttm(quarters, i, _revenue)
                    )
                )
                is None
                else r * D(365),
                None,
            ),
        )
        _cash(out, quarters, b)

    if market is not None:
        _valuation(out, quarters, market, qb)
    return out


def _npa(q: Quarter, name: str) -> Decimal | None:
    """Banks' filings often carry 0 where the figure is simply not given; a bank with exactly zero bad loans is not a thing."""
    v = _pick(q.quarter, name)
    return v if v is not None and v > 0 else None


def _on_equity(q: Quarter, value: Decimal | None) -> tuple[Decimal | None, str | None]:
    """A ratio over owners' equity means nothing when equity is zero or negative (accumulated losses exceed capital)."""
    eq = _equity(q)
    if eq is not None and eq <= 0:
        return None, "owners' equity is zero or negative, so this ratio means nothing"
    return value, None


def _net_debt_cover(qs: Sequence[Quarter], q: Quarter, i: int) -> tuple[Decimal | None, str | None]:
    debt, ebitda = _debt(q), _ttm(qs, i, _operating)
    if debt is None or ebitda is None:
        return None, None
    if ebitda <= 0:
        return None, "operating profit is zero or negative"
    return (debt - _liquid(q)) / ebitda, None


def _interest_cover(qs: Sequence[Quarter], i: int) -> tuple[Decimal | None, str | None]:
    ebit, interest = _ttm(qs, i, _ebit), _ttm(qs, i, lambda q: _pick(q.quarter, "FinanceCosts"))
    if ebit is None or interest is None:
        return None, None
    return (None, "no interest cost") if interest == 0 else (ebit / interest, None)


def _cash(out: dict[str, RatioValue], qs: Sequence[Quarter], b: int | None) -> None:
    """Cash flow is cumulative from the start of the financial year: use the latest quarter that carries it."""
    c = next((q for q in qs if "CashFlowsFromUsedInOperatingActivities" in q.ytd), None)
    if c is None:
        for k in ("cfo_to_profit", "free_cash_flow", "fcf_margin"):
            out[k] = RatioValue(None, "no cash flow statement filed yet")
        return
    cfo = c.ytd["CashFlowsFromUsedInOperatingActivities"]
    pat = _pat(c.ytd)
    out["cfo_to_profit"] = RatioValue(
        _div(cfo, pat) if pat is not None and pat > 0 else None,
        None if pat is not None and pat > 0 else "profit is zero or a loss",
        c.period_end,
    )
    capex = (
        _pick(c.ytd, "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities") or ZERO
    ) + (_pick(c.ytd, "PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities") or ZERO)
    fcf = cfo - capex
    out["free_cash_flow"] = RatioValue(fcf / D(10_000_000), None, c.period_end)
    margin = _pct(fcf, _pick(c.ytd, "RevenueFromOperations", "Income"))
    note = None if margin is not None else "sales for the year so far not reported"
    out["fcf_margin"] = RatioValue(margin, note, c.period_end)


def _valuation(
    out: dict[str, RatioValue], qs: Sequence[Quarter], m: Market, qb: Quarter | None
) -> None:
    q0 = qs[0]
    keys = ["market_cap", "pe", "pb", "earnings_yield", "dividend_yield"] + (
        [] if q0.bank else ["ps", "ev_ebitda"]
    )
    why = None
    if m.price is None or m.price <= 0:
        why = "no price"
    elif m.split_since_results:
        why = "a split or bonus since the latest results puts price and results on different bases"
    paid, face = (
        _pick(q0.quarter, "PaidUpValueOfEquityShareCapital"),
        _pick(q0.quarter, "FaceValueOfEquityShareCapital"),
    )
    shares = _div(paid, face)
    if why is None and shares is None:
        why = "share count not in the filing"
    if why is not None or m.price is None or shares is None:
        for k in keys:
            out[k] = RatioValue(None, why)
        return
    price, day = m.price, m.price_date
    cap = price * shares
    out["market_cap"] = RatioValue(cap / D(10_000_000), None, day)
    eps = _ttm(qs, 0, _eps)
    if eps is None:
        out["pe"] = out["earnings_yield"] = RatioValue(
            None, "needs four consecutive quarters of earnings per share", day
        )
    elif eps <= 0:
        out["pe"] = out["earnings_yield"] = RatioValue(
            None, "loss-making over the last 12 months: P/E is not meaningful", day
        )
    else:
        out["pe"], out["earnings_yield"] = (
            RatioValue(price / eps, None, day),
            RatioValue(eps / price * HUNDRED, None, day),
        )
    eq = _equity(qb) if qb else None
    out["pb"] = (
        RatioValue(price / (eq / shares), None, day)
        if eq and eq > 0
        else RatioValue(None, "owners' equity is missing, zero or negative", day)
    )
    dps = m.dividend_per_share_12m
    out["dividend_yield"] = RatioValue(
        None if dps is None else dps / price * HUNDRED,
        "no dividend data" if dps is None else None,
        day,
    )
    if q0.bank:
        return
    rev = _ttm(qs, 0, _revenue)
    out["ps"] = RatioValue(
        _div(cap, rev), "needs four consecutive quarters" if not rev else None, day
    )
    ebitda = _ttm(qs, 0, _operating)
    debt = _debt(qb) if qb else None
    if ebitda is None or debt is None or ebitda <= 0 or qb is None:
        out["ev_ebitda"] = RatioValue(
            None, "needs a balance sheet and positive operating profit", day
        )
    else:
        out["ev_ebitda"] = RatioValue((cap + debt - _liquid(qb)) / ebitda, None, day)
