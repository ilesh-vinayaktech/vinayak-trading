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
    kind: str  # fundamental | technical | profile
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
FIELDS: dict[str, Field] = {
    **{r.key: Field(r.key, r.label, r.group, "fundamental", r.unit) for r in RATIOS},
    **{k: Field(k, label, g, "technical", u) for k, label, g, u in _TECH},
    "segment": Field("segment", "Market-cap class (AMFI)", "profile", "profile", "text"),
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
