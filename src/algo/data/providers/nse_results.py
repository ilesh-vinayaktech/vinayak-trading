# ruff: noqa: E501  (docstrings and one-line mappings are kept readable)
"""NSE quarterly financial results: the filing listing (JSON) and the XBRL statement of each filing.

Pure parsing, no HTTP. The listing gives each filing's exact broadcast time (the point-in-time date: nothing in a
filing may be used before it). The XBRL gives the P&L in full rupees for the quarter and the year to date, standalone
or consolidated. Values from segment or other dimensional contexts are never read as company totals, a line that was
not reported is absent (not zero), and anything ambiguous is refused with XbrlError."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET  # noqa: S405 - DOCTYPE/ENTITY are rejected before parsing
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
XBRLI = "{http://www.xbrl.org/2003/instance}"

# metric -> XBRL element names in priority order (non-banks first, then the banking taxonomy)
METRICS: dict[str, tuple[str, ...]] = {
    "revenue": ("RevenueFromOperations", "Income"),
    "total_income": ("Income",),
    "other_income": ("OtherIncome",),
    "interest_earned": ("InterestEarned",),
    "interest_expended": ("InterestExpended",),
    "operating_profit": ("OperatingProfitBeforeProvisionAndContingencies",),
    "provisions": ("ProvisionsOtherThanTaxAndContingencies",),
    "expenses": ("Expenses", "ExpenditureExcludingProvisionsAndContingencies"),
    "finance_costs": ("FinanceCosts",),
    "depreciation": ("DepreciationDepletionAndAmortisationExpense",),
    "pbt": ("ProfitBeforeTax", "ProfitLossFromOrdinaryActivitiesBeforeTax"),
    "tax": ("TaxExpense",),
    "pat": ("ProfitLossForPeriod", "ProfitLossForThePeriod"),
    "pat_owners": (
        "ProfitOrLossAttributableToOwnersOfParent",
        "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates",
    ),
    "eps_basic": (
        "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
        "BasicEarningsPerShareAfterExtraordinaryItems",
    ),
    "eps_diluted": (
        "DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
        "DilutedEarningsPerShareAfterExtraordinaryItems",
    ),
}


class XbrlError(Exception):
    pass


@dataclass(frozen=True)
class Filing:
    symbol: str
    isin: str
    seq_number: str
    period_start: date
    period_end: date
    basis: str  # STANDALONE | CONSOLIDATED
    audited: bool
    bank: bool
    cumulative: bool
    filed_at: (
        datetime | None
    )  # NSE broadcast time, UTC; None for old filings that have none (never guessed)
    disseminated_at: datetime | None
    xbrl_url: str | None
    detail_url: str | None  # older filings: an HTML page instead of XBRL


@dataclass(frozen=True)
class Statement:
    period_start: date
    period_end: date
    basis: str
    audited: bool
    rounding: str
    quarter: dict[str, Decimal]
    ytd: dict[str, Decimal]


def _stamp(text: str) -> datetime:
    return datetime.strptime(text, "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST).astimezone(UTC)  # noqa: DTZ007


def _day(text: str) -> date:
    return datetime.strptime(text, "%d-%b-%Y").date()  # noqa: DTZ007


def _link(value: Any) -> str | None:
    return None if not value or str(value).rstrip("/").endswith("-") else str(value)


def parse_listing(raw: bytes) -> list[Filing]:
    try:
        rows = json.loads(raw)
    except ValueError as e:
        raise XbrlError("not a results listing") from e
    if not isinstance(rows, list):
        raise XbrlError("not a results listing")
    return [
        Filing(
            symbol=r["symbol"], isin=r["isin"], seq_number=str(r["seqNumber"]),
            period_start=_day(r["fromDate"]), period_end=_day(r["toDate"]),
            basis="CONSOLIDATED" if r["consolidated"] == "Consolidated" else "STANDALONE",
            audited=r["audited"] == "Audited", bank=r["bank"] == "B",
            cumulative=str(r["cumulative"]).startswith("Cumulative"), filed_at=_stamp(r["broadCastDate"]) if r.get("broadCastDate") else None,
            disseminated_at=_stamp(r["exchdisstime"]) if r.get("exchdisstime") else None,
            xbrl_url=_link(r.get("xbrl")), detail_url=_link(r.get("resultDetailedDataLink")),
        )
        for r in rows
    ]  # fmt: skip


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_xbrl(raw: bytes) -> Statement:
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise XbrlError("not an XBRL instance (DTD/entity declarations refused)")
    try:
        root = ET.fromstring(raw)  # noqa: S314
    except ET.ParseError as e:
        raise XbrlError("not an XBRL instance") from e
    if _local(root.tag) != "xbrl":
        raise XbrlError("not an XBRL instance")
    # A referenced context is the company as a whole unless it is DEFINED with a segment / dimension. Older NSE
    # files reference the standard contexts (OneD, FourD, ...) without defining them at all.
    dimensional: set[str] = set()
    for ctx in root.iter(f"{XBRLI}context"):
        if any(_local(m.tag) in ("explicitMember", "typedMember") for m in ctx.iter()):
            dimensional.add(ctx.get("id", ""))
    facts: dict[tuple[str, str], str] = {}
    for el in root:
        ref = el.get("contextRef")
        if ref is not None and ref not in dimensional:
            facts.setdefault((_local(el.tag), ref), (el.text or "").strip())

    def first(name: str) -> str | None:
        return next((v for (n, _), v in facts.items() if n == name and v), None)

    # NSE declares each context's period in header facts (the quarter in OneD, the year to date in FourD);
    # the context's own start/end dates are the quarter in both, so they are not used.
    periods: dict[str, tuple[date, date]] = {}
    for i in {k[1] for k in facts}:
        end_t = facts.get(("DateOfEndOfReportingPeriod", i))
        if not end_t:
            continue
        end_d = date.fromisoformat(end_t)
        start_t = facts.get(("DateOfStartOfReportingPeriod", i))
        if start_t:
            periods[i] = (date.fromisoformat(start_t), end_d)
        elif (
            i.startswith("One")
            and (end_d + timedelta(days=1)).day == 1
            and end_d.month in (3, 6, 9, 12)
        ):
            # older files give only the end: by the taxonomy convention OneD is the current quarter, so
            # the quarter starts on the first day of the calendar quarter that ends here
            periods[i] = (
                date(end_d.year if end_d.month > 3 else end_d.year, end_d.month - 2, 1),
                end_d,
            )
        elif i.startswith("Four") and first("DateOfStartOfFinancialYear"):
            periods[i] = (date.fromisoformat(first("DateOfStartOfFinancialYear") or ""), end_d)
    if not periods:
        raise XbrlError("no reporting period in the statement")
    quarters = {i: sp for i, sp in periods.items() if 80 <= (sp[1] - sp[0]).days <= 100}
    if not quarters:
        raise XbrlError(f"reporting periods {sorted(set(periods.values()))} contain no quarter")
    start, end = max(quarters.values(), key=lambda sp: sp[1])
    nature = (first("NatureOfReportStandaloneConsolidated") or "").lower()
    if nature.startswith("consolidated"):
        basis = "CONSOLIDATED"
    elif nature.startswith(("standalone", "non")):
        basis = "STANDALONE"
    else:
        raise XbrlError("statement is neither standalone or consolidated")
    audited = (first("WhetherResultsAreAuditedOrUnaudited") or "").lower().startswith("audited")
    q_ids = [i for i, sp in quarters.items() if sp == (start, end)]
    longer = {
        i: sp
        for i, sp in periods.items()
        if sp[1] == end and sp[0] < start and (end - sp[0]).days <= 370
    }
    y_ids = [min(longer, key=lambda i: longer[i][0])] if longer else []

    def take(ids: list[str]) -> dict[str, Decimal]:
        out: dict[str, Decimal] = {}
        for metric, names in METRICS.items():
            for name in names:
                v = next((facts[(name, i)] for i in ids if facts.get((name, i))), None)
                if v is not None:
                    try:
                        out[metric] = Decimal(v)
                    except InvalidOperation as e:
                        raise XbrlError(f"{name}: {v!r} is not a number") from e
                    break
        return out

    rounding = first("LevelOfRoundingUsedInFinancialStatements") or ""
    return Statement(start, end, basis, audited, rounding, take(q_ids), take(y_ids))
