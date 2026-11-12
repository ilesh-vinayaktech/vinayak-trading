# ruff: noqa: E501
"""AMFI's half-yearly "Average Market Capitalization of listed companies" -> market-cap segment of every company.

SEBI's circular of 6 Oct 2017 defines large cap as ranks 1-100 by average full market cap, mid cap 101-250 and small cap 251
onwards; AMFI publishes the ranking every six months (periods ending 30 June and 31 December). Micro cap has no official
definition: here it is rank 501 onwards (the band Nifty Microcap 250 starts from), so small cap is 251-500.
A list is relied on only from the first day of the second month after its period (30 June -> 1 August): it is published in
the first days of the next month, and the month's margin keeps a backtest from knowing it a day early.
Every list read so far (Jun 2018 .. Jun 2026) has exactly 100 Large and 150 Mid; a file whose labels disagree with its ranks,
whose ranks skip, or whose columns are not where expected is refused whole rather than read half right."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from algo.data.providers.xlsx_table import is_xlsx, xlsx_rows

MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"), 1)}  # fmt: skip
PERIOD = re.compile(r"six months ended (\d{1,2})(?:st|nd|rd|th)? ([a-z]+),? (\d{4})", re.I)
COLUMNS = {
    "rank": "sr",
    "name": "company",
    "isin": "isin",
    "nse_symbol": "nse symbol",
    "avg_cap": "average of all",
    "category": "categori",
}
ISIN = re.compile(r"^IN[A-Z0-9]{10}$")
SEGMENTS = (("large", 100), ("mid", 250), ("small", 500))
AMFI_LABEL = {
    "large": "Large Cap",
    "mid": "Mid Cap",
    "small": "Small Cap",
    "micro": "Small Cap",
}  # AMFI has no micro


class AmfiError(ValueError):
    pass


@dataclass(frozen=True)
class CapRow:
    rank: int
    isin: str | None  # None: AMFI prints 'NA' for some old BSE-only companies; they keep their rank
    nse_symbol: str | None
    name: str
    avg_cap: Decimal  # average full market cap over the six months, across exchanges, Rs crore


@dataclass(frozen=True)
class CapList:
    period_end: date
    rows: tuple[CapRow, ...]


def segment_of(rank: int) -> str:
    return next((name for name, last in SEGMENTS if rank <= last), "micro")


def effective_from(period_end: date) -> date:
    month = period_end.month + 2
    return date(period_end.year + (month - 1) // 12, (month - 1) % 12 + 1, 1)


def _period(text: str) -> date:
    m = PERIOD.search(text)
    if m is None or m.group(2).lower() not in MONTHS:
        raise AmfiError(f"no 'six months ended <date>' period in the title: {text[:120]!r}")
    return date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))


def parse_list(raw: bytes) -> CapList:
    if not is_xlsx(raw):
        raise AmfiError("not a spreadsheet")
    rows = xlsx_rows(raw)
    at = next((i for i, r in enumerate(rows[:10]) if any("ISIN" in c for c in r)), None)
    header = [c.strip().lower() for c in rows[at]] if at is not None else []
    cols = {
        k: next((i for i, h in enumerate(header) if h.startswith(n) or n in h), None)
        for k, n in COLUMNS.items()
    }
    missing = sorted(k for k, i in cols.items() if i is None)
    if at is None or missing:
        raise AmfiError(f"columns not found: {', '.join(missing) or 'no header row'}")
    period_end = _period(" ".join(c for r in rows[:at] for c in r if c))
    out: list[CapRow] = []
    for r in rows[at + 1 :]:
        if not r or not r[0].strip().isdigit():
            continue  # notes or blank lines around the table

        def cell(key: str, r: list[str] = r) -> str:
            i = cols[key]
            return r[i].strip() if i is not None and i < len(r) else ""

        if not any(r[1:]):
            continue  # a serial number with nothing else (the Jun 2023 list ends with nine): not a company
        rank = int(cell("rank"))
        if rank != len(out) + 1 and not (
            out and rank == out[-1].rank
        ):  # equal caps share a rank (1, 2, 2, 4)
            raise AmfiError(
                f"ranks are not 1, 2, 3... (ties allowed): {rank} at position {len(out) + 1}"
            )
        isin = cell("isin")
        if isin not in ("", "NA") and not ISIN.match(isin):
            raise AmfiError(f"bad ISIN {isin!r} at rank {rank}")
        label, expected = cell("category"), AMFI_LABEL[segment_of(rank)]
        if label != expected:
            raise AmfiError(
                f"rank {rank} is labelled {label!r}, but AMFI's own rule makes it {expected!r}"
            )
        try:
            cap = Decimal(cell("avg_cap"))
        except InvalidOperation as e:
            raise AmfiError(f"bad market cap {cell('avg_cap')!r} at rank {rank}") from e
        nse = cell("nse_symbol")
        out.append(
            CapRow(
                rank,
                isin if ISIN.match(isin) else None,
                None if nse in ("", "-") else nse,
                cell("name"),
                cap,
            )
        )
    if not out:
        raise AmfiError("no companies in the list")
    return CapList(period_end, tuple(out))
