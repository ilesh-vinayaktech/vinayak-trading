# ruff: noqa: E501
"""The screener's fields and condition engine. Pure: it filters and sorts rows (dicts of field -> Decimal / str / bool / None).
A missing value (None) never matches a condition, so "unknown" is never read as zero."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from algo.data.ratios import RATIOS

Row = Mapping[str, Any]


class ScreenError(ValueError):
    pass


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    group: str  # valuation | profitability | growth | strength | efficiency | cash | momentum | trend | volume | profile
    kind: str  # fundamental | technical | profile | smart_money | score
    unit: str  # pct | x | days | crore | inr | text


_TECH = (
    ("price", "Last close", "trend", "inr"),
    ("chg_1d", "Change, 1 day", "momentum", "pct"),
    ("chg_1w", "Change, 1 week", "momentum", "pct"),
    ("chg_1m", "Change, 1 month", "momentum", "pct"),
    ("chg_3m", "Change, 3 months", "momentum", "pct"),
    ("chg_6m", "Change, 6 months", "momentum", "pct"),
    ("chg_1y", "Change, 1 year", "momentum", "pct"),
    ("rsi_14", "RSI (14)", "momentum", "x"),
    ("macd_hist", "MACD histogram", "momentum", "x"),
    ("adx_14", "ADX (14), trend strength", "trend", "x"),
    ("price_vs_sma50", "Price vs 50-day average", "trend", "pct"),
    ("price_vs_sma200", "Price vs 200-day average", "trend", "pct"),
    ("sma50_vs_sma200", "50-day vs 200-day average", "trend", "pct"),
    ("pct_from_52w_high", "From 52-week high", "trend", "pct"),
    ("pct_from_52w_low", "From 52-week low", "trend", "pct"),
    ("volume_ratio", "Volume vs 20-day average", "volume", "x"),
    ("turnover_cr", "Daily traded value (20-day avg)", "volume", "crore"),
)
# (key, label, group, unit) of the NSE delivery / ownership / insider / deal fields; computed by algo.screener.smart_money
SMART_MONEY_FIELDS: tuple[tuple[str, str, str, str], ...] = (
    ("delivery_pct", "Delivery %, last session", "delivery", "pct"),
    ("delivery_pct_20d", "Delivery %, 20-session average", "delivery", "pct"),
    ("delivery_vs_avg", "Delivery % vs its 20-session average (1 = same)", "delivery", "x"),
    ("promoter_pct", "Promoter holding", "ownership", "pct"),
    ("fii_pct", "FII / FPI holding", "ownership", "pct"),
    ("dii_pct", "DII holding (mutual funds, insurers, banks ...)", "ownership", "pct"),
    ("mf_pct", "Mutual fund holding", "ownership", "pct"),
    ("retail_pct", "Retail holding (up to Rs 2 lakh)", "ownership", "pct"),
    ("promoter_change", "Promoter holding, change since last quarter (points)", "ownership", "pct"),
    ("fii_change", "FII / FPI holding, change since last quarter (points)", "ownership", "pct"),
    ("dii_change", "DII holding, change since last quarter (points)", "ownership", "pct"),
    ("mf_change", "Mutual fund holding, change since last quarter (points)", "ownership", "pct"),
    ("insider_net_90d", "Insider net buying, 90 days", "insider", "crore"),
    ("insider_buys_90d", "Insider buy filings, 90 days", "insider", "x"),
    ("deal_net_30d", "Bulk and block deals, net buying, 30 days", "deals", "crore"),
)
# the swing score and its parts (algo.screener.score), 0 to 100; built from the fields above incl. smart money; the numeric ones (not setup / score_why) CAN drive a strategy because they are read from stock_score_history, each built from what was known on its own day (algo.strategies.scorebook); today's values here are for looking
SCORE_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("score", "Swing score (0 to 100)", "x"),
    ("score_trend", "Score: trend", "x"),
    ("score_participation", "Score: volume and delivery", "x"),
    ("score_smart_money", "Score: smart money", "x"),
    ("score_quality", "Score: quality", "x"),
)
# the market zone as known on the day (algo.market, table market_regime_daily): the same value for every stock, so it is a REGIME FILTER inside a screen ("only while the market is not in extreme fear")
MARKET_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("mkt_fear_greed", "Market fear/greed (0 extreme fear to 100 extreme greed)", "x"),
    ("mkt_bull", "Market is in a bull regime (1 yes, 0 no)", "x"),
    ("mkt_stressed", "Market volatility is stressed (1 yes, 0 no)", "x"),
)
FIELDS: dict[str, Field] = {
    **{r.key: Field(r.key, r.label, r.group, "fundamental", r.unit) for r in RATIOS},
    **{k: Field(k, label, g, "technical", u) for k, label, g, u in _TECH},
    **{k: Field(k, label, g, "smart_money", u) for k, label, g, u in SMART_MONEY_FIELDS},
    **{k: Field(k, label, "score", "score", u) for k, label, u in SCORE_FIELDS},
    **{k: Field(k, label, "market", "score", u) for k, label, u in MARKET_FIELDS},
    "setup": Field("setup", "Setup flags (breakout, accumulation, ...)", "score", "score", "text"),
    "score_why": Field("score_why", "Why it scores", "score", "score", "text"),
    "segment": Field("segment", "Market-cap class (AMFI)", "profile", "profile", "text"),
    "sector": Field("sector", "Sector (NSE industry)", "profile", "profile", "text"),
    "pe_sector_median": Field(
        "pe_sector_median", "P/E, median of its sector peers", "valuation", "profile", "x"
    ),
    "pe_vs_sector": Field(
        "pe_vs_sector", "P/E relative to its sector peers (1 = same)", "valuation", "profile", "x"
    ),
}
NUMERIC_OPS = {"gt", "gte", "lt", "lte", "eq", "ne", "between"}
TEXT_OPS = {"eq", "ne", "in"}


@dataclass(frozen=True)
class Condition:
    field: str
    op: str
    value: Any  # number-like, [lo, hi] for between, a string or list of strings for text fields


def _num(v: Any) -> Decimal:
    try:
        d = Decimal(str(v))
    except InvalidOperation as e:
        raise ScreenError(f"{v!r} is not a number") from e
    if not d.is_finite():
        raise ScreenError(f"{v!r} is not a number")
    return d


def validate(c: Condition) -> None:
    f = FIELDS.get(c.field)
    if f is None:
        raise ScreenError(f"unknown field {c.field!r}")
    if f.unit == "text":
        if c.op not in TEXT_OPS:
            raise ScreenError(f"{c.field}: use one of {sorted(TEXT_OPS)}")
        if c.op == "in" and not isinstance(c.value, list | tuple):
            raise ScreenError(f"{c.field}: 'in' needs a list")
        return
    if c.op not in NUMERIC_OPS:
        raise ScreenError(f"{c.field}: use one of {sorted(NUMERIC_OPS)}")
    if c.op == "between":
        if not isinstance(c.value, list | tuple) or len(c.value) != 2:
            raise ScreenError(f"{c.field}: between needs [low, high]")
        lo, hi = _num(c.value[0]), _num(c.value[1])
        if lo > hi:
            raise ScreenError(f"{c.field}: low is above high")
    else:
        _num(c.value)


def matches(row: Row, c: Condition) -> bool:
    v = row.get(c.field)
    if v is None:
        return False
    if FIELDS[c.field].unit == "text":
        return bool((v in c.value) if c.op == "in" else ((v == c.value) == (c.op == "eq")))
    if c.op == "between":
        return bool(_num(c.value[0]) <= v <= _num(c.value[1]))
    t = _num(c.value)
    return bool(
        {"gt": v > t, "gte": v >= t, "lt": v < t, "lte": v <= t, "eq": v == t, "ne": v != t}[c.op]
    )


def run(
    rows: Sequence[Row],
    conditions: Sequence[Condition],
    *,
    match: str = "all",
    sort: str | None = None,
    descending: bool = True,
    limit: int = 100,
) -> tuple[list[Row], int]:
    """(the first `limit` matching rows in order, how many matched). Rows without a value for `sort` go last."""
    for c in conditions:
        validate(c)
    if sort is not None and sort not in FIELDS:
        raise ScreenError(f"unknown sort field {sort!r}")
    if match not in ("all", "any"):
        raise ScreenError("match must be 'all' or 'any'")
    pick = all if match == "all" else any
    hit = [r for r in rows if conditions and pick(matches(r, c) for c in conditions)]
    if sort is not None:
        have = sorted(
            (r for r in hit if r.get(sort) is not None), key=lambda r: r[sort], reverse=descending
        )
        hit = have + [r for r in hit if r.get(sort) is None]
    return hit[:limit], len(hit)
