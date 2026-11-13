# ruff: noqa: E501
"""The returns table of an NSE Indices factsheet (the PDF's text, from `pdftotext -layout`) and the checks it gives for the stored
levels. Pure. Bases follow the convention read off the Nifty 200 / Nifty 50 sheets: QTD from the previous quarter end, YTD from
the previous 31 Dec, 1 year from the last session on or before (end - 1 year + 1 day), 5 years from the last session on or before
(end - 5 years). The 5-year rule is the one that reconciles the 2024 Nifty Capital Markets sheet (the +1 day rule is a day out) and
every other index's; it gives the same base as the +1 day rule on the Nifty 200 sheet."""

from __future__ import annotations

import re
from collections.abc import Collection
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

_DATE = re.compile(r"\b([A-Z][a-z]+ \d{1,2}, \d{4})\b")
_ROW = r"{} Return\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)"
LABELS = ("QTD", "YTD", "1 year", "5 years (CAGR)")


class FactsheetError(ValueError):
    pass


def parse(text: str) -> tuple[date, dict[str, tuple[str, ...]]]:
    """(as-of date, {'price': 5 figures, 'total': 5 figures}); a figure is a number or '-'. QTD, YTD, 1y, 5y, since inception."""
    m = _DATE.search(text)
    if m is None:
        raise FactsheetError("no document date")
    as_of = datetime.strptime(m.group(1), "%B %d, %Y").replace(tzinfo=UTC).date()
    rows: dict[str, tuple[str, ...]] = {}
    for key, word in (("price", "Price"), ("total", "Total")):
        r = re.search(_ROW.format(word), text)
        if r is None:
            raise FactsheetError(f"no {word} Return row")
        rows[key] = r.groups()
    return as_of, rows


def _on_or_before(day: date, days: Collection[date]) -> date:
    while day not in days:
        day -= timedelta(days=1)
        if day.year < 1990:
            raise FactsheetError("no session before the base date")
    return day


def _years_back(end: date, n: int) -> date:
    try:
        return end.replace(year=end.year - n)
    except ValueError:  # 29 Feb
        return end.replace(year=end.year - n, day=28)


def build_checks(
    as_of: date, total: tuple[str, ...], days: Collection[date]
) -> list[dict[str, Any]]:
    """Total-return checks for the figures that are published (not '-') and whose base falls inside the stored history."""
    q_end = date(as_of.year, 3 * ((as_of.month - 1) // 3) + 1, 1) - timedelta(days=1)
    bases = [
        ("QTD", q_end, "cumulative", "0.005"),
        ("YTD", date(as_of.year - 1, 12, 31), "cumulative", "0.005"),
        ("1 year", _years_back(as_of, 1) + timedelta(days=1), "cumulative", "0.005"),
        ("5 years (CAGR)", _years_back(as_of, 5), "cagr", "0.02"),
    ]
    first = min(days)
    out = []
    for (label, base, kind, tol), figure in zip(bases, total[:4], strict=True):
        if figure == "-" or base < first:
            continue
        out.append(
            {
                "label": label,
                "base": _on_or_before(base, days).isoformat(),
                "end": as_of.isoformat(),
                "kind": kind,
                "total_return_pct": str(Decimal(figure)),
                "tolerance_pp": tol,
                "series": "gross",
            }
        )
    return out
