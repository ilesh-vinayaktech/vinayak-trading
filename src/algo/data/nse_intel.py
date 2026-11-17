# ruff: noqa: E501
"""NSE market intelligence: bulk/block deals, insider (PIT) trades, shareholding pattern headline, FII/DII cash flows.

Each `parse_*` is pure (raw bytes -> typed rows, `ParseError` on a shape change); each `store_*` inserts with
ON CONFLICT DO NOTHING and returns how many rows were NEW, so a poll of an overlapping window is free and "anything new?"
is just a count. Delivery % and most-active are derived from the stored daily bars, not fetched: NSE's own lists are the
same numbers (bhavcopy), and this way they exist for every past day too."""

from __future__ import annotations

import csv
import io
import json
import re
import xml.etree.ElementTree as ET  # noqa: S405  (NSE's own filings, not user input)
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

import psycopg

from algo.data.providers.base import ParseError

IST = ZoneInfo("Asia/Kolkata")
BASE = "https://www.nseindia.com"
WARM = f"{BASE}/companies-listing/corporate-filings-insider-trading"
DEALS_HISTORY_URL = "https://www.nseindia.in/api/historicalOR/bulk-block-short-deals?optionType={kind}_deals&from={start:%d-%m-%Y}&to={end:%d-%m-%Y}&csv=true"  # the report page's own download, any window (the JSON form is capped at 70 rows)
DEALS_HISTORY_WARM = "https://www.nseindia.in/report-detail/display-bulk-and-block-deals"
BULK_URL = "https://nsearchives.nseindia.com/content/equities/bulk.csv"  # latest session only
BLOCK_URL = "https://nsearchives.nseindia.com/content/equities/block.csv"  # latest session only
FII_DII_URL = f"{BASE}/api/fiidiiTradeReact"  # latest session only
SHAREHOLDING_HISTORY_URL = "https://www.nseindia.in/api/corporate-share-holdings-master?index=equities&from_date={start:%d-%m-%Y}&to_date={end:%d-%m-%Y}"  # by FILING date; full coverage only from the Sep-2021 quarter
SHAREHOLDING_URL = (
    f"{BASE}/api/corporate-share-holdings-master?index=equities"  # latest quarter, all companies
)
INSIDER_INDEX_URL = f"{BASE}/api/corporates-pit-gg?index=equities&from_date={{start:%d-%m-%Y}}&to_date={{end:%d-%m-%Y}}"  # from 2026-05-03: one row per filing
INSIDER_URL = f"{BASE}/api/corporates-pit?index=equities&from_date={{start:%d-%m-%Y}}&to_date={{end:%d-%m-%Y}}"


def _num(v: Any) -> Decimal | None:
    if v is None or str(v).strip() in ("", "-"):
        return None
    try:
        return Decimal(str(v).replace(",", "").strip())
    except InvalidOperation:
        return None


def _date(v: Any) -> date | None:
    if v is None or str(v).strip() in ("", "-"):
        return None
    for fmt in ("%d-%b-%Y", "%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(v).strip(), fmt).date()  # noqa: DTZ007  (a calendar date, no zone)
        except ValueError:
            continue
    return None


def _ist_to_utc(v: Any) -> datetime | None:
    """NSE broadcast stamps are Indian time without a zone; stored as UTC."""
    if v is None or str(v).strip() in ("", "-"):
        return None
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M"):
        try:
            return datetime.strptime(str(v).strip(), fmt).replace(tzinfo=IST).astimezone(UTC)  # noqa: DTZ007
        except ValueError:
            continue
    return None


def _text(v: Any) -> str | None:
    s = None if v is None else str(v).strip()
    return None if s in (None, "", "-") else s


def _json_list(raw: bytes, key: str | None = None) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw)
        rows = data[key] if key else data
        if not isinstance(rows, list):
            raise ParseError("expected a list")
        return rows
    except (ValueError, KeyError, TypeError) as e:
        raise ParseError(str(e)) from e


# ---------------------------------------------------------------- bulk / block deals


def parse_deals(raw: bytes, kind: str) -> list[tuple[Any, ...]]:
    """The daily file and the report page's download differ in header spacing ("Buy/Sell" vs "Buy / Sell ") and number format ("66,829"): both parse."""
    text = raw.decode("utf-8-sig")
    out: list[tuple[Any, ...]] = []
    try:
        for raw_row in csv.DictReader(io.StringIO(text)):
            r = {re.sub(r"\s+", "", k or ""): (v or "").strip() for k, v in raw_row.items()}
            if r.get("Date", "").upper().replace(" ", "") == "NORECORDS":
                continue
            side = r["Buy/Sell"].upper()
            qty, price = _num(r["QuantityTraded"]), _num(r["TradePrice/Wght.Avg.Price"])
            d = _date(r["Date"])
            if d is None or qty is None or price is None or side not in ("BUY", "SELL"):
                raise ParseError(f"bad deal row: {raw_row}")
            out.append(
                (kind, d, r["Symbol"], r["ClientName"], side, qty, price, _text(r.get("Remarks")))
            )
    except KeyError as e:
        raise ParseError(f"missing column {e}") from e
    return out


def store_deals(conn: psycopg.Connection, rows: Iterable[tuple[Any, ...]], now: datetime) -> int:
    return _insert(
        conn,
        "INSERT INTO nse_bulk_block_deal (kind, trade_date, symbol, client, side, quantity, price, remarks, ingested_at)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
        [(*r, now) for r in rows],
    )


# ---------------------------------------------------------------- FII / DII


def parse_fii_dii(raw: bytes) -> list[tuple[Any, ...]]:
    out = []
    for r in _json_list(raw):
        try:
            cat = {"FII/FPI": "FII", "DII": "DII"}[r["category"]]
            vals = (_num(r["buyValue"]), _num(r["sellValue"]), _num(r["netValue"]))
            d = _date(r["date"])
        except KeyError as e:
            raise ParseError(f"missing {e}") from e
        if d is None or None in vals:
            raise ParseError(f"bad FII/DII row: {r}")
        out.append((d, cat, *vals))
    return out


def store_fii_dii(conn: psycopg.Connection, rows: Iterable[tuple[Any, ...]], now: datetime) -> int:
    return _insert(
        conn,
        "INSERT INTO nse_fii_dii (trade_date, category, buy_value, sell_value, net_value, ingested_at)"
        " VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
        [(*r, now) for r in rows],
    )


# ---------------------------------------------------------------- insider trading (SEBI PIT), the old list (to 2026-05-02)


def parse_insider(raw: bytes) -> list[tuple[Any, ...]]:
    out = []
    for r in _json_list(raw, "data"):
        try:
            out.append((
                str(r["did"]), r["symbol"], r["acqName"], _text(r.get("personCategory")),
                _text(r.get("tdpTransactionType")), _text(r.get("acqMode")), _text(r.get("secType")),
                _num(r.get("secAcq")), _num(r.get("secVal")),
                _num(r.get("befAcqSharesNo")), _num(r.get("befAcqSharesPer")),
                _num(r.get("afterAcqSharesNo")), _num(r.get("afterAcqSharesPer")),
                _date(r.get("acqfromDt")), _date(r.get("acqtoDt")), _date(r.get("intimDt")),
                _ist_to_utc(r.get("date")), _text(r.get("xbrl")),
            ))  # fmt: skip
        except KeyError as e:
            raise ParseError(f"missing {e}") from e
    return out


def store_insider(conn: psycopg.Connection, rows: Iterable[tuple[Any, ...]], now: datetime) -> int:
    return _insert(
        conn,
        "INSERT INTO nse_insider_trade (did, symbol, person, person_category, transaction_type, acquisition_mode,"
        " security_type, quantity, value, shares_before, pct_before, shares_after, pct_after, from_date, to_date,"
        " intimation_date, broadcast_at, xbrl_url, ingested_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
        " ON CONFLICT DO NOTHING",
        [(*r, now) for r in rows],
    )


# ---------------------------------------------------------------- insider trading (SEBI PIT), the new list: filing index + the inline-XBRL file of each


def parse_pit_index(raw: bytes) -> list[tuple[Any, ...]]:
    out = []
    try:
        data = json.loads(raw)["data"] or []
    except (ValueError, KeyError, TypeError) as e:
        raise ParseError(str(e)) from e
    for r in data:
        try:
            out.append((
                str(r["appId"]), r["symbol"], _text(r.get("companyName")), _text(r.get("regulation")), _text(r.get("typeOfSubmission")),
                _text(r.get("prevAppId")), _ist_to_utc(r.get("broadcastDateTime")), _text(r.get("ixbrl")),
            ))  # fmt: skip
        except KeyError as e:
            raise ParseError(f"missing {e}") from e
    return out


def store_pit_index(
    conn: psycopg.Connection, rows: Iterable[tuple[Any, ...]], now: datetime
) -> int:
    """New filings stored. A revision replaces the filing it names: that filing is marked superseded and its parsed trades removed."""
    new = _insert(
        conn,
        "INSERT INTO nse_insider_filing (app_id, symbol, company, regulation, submission_type, prev_app_id, broadcast_at, ixbrl_url, ingested_at)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
        [(*r, now) for r in rows],
    )
    conn.execute(
        "UPDATE nse_insider_filing o SET superseded = true FROM nse_insider_filing r WHERE r.prev_app_id = o.app_id AND NOT o.superseded"
    )
    conn.execute(
        "DELETE FROM nse_insider_trade t USING nse_insider_filing f WHERE f.superseded AND t.did LIKE f.app_id || ':%'"
    )
    return new


def pending_pit_details(
    conn: psycopg.Connection, limit: int
) -> list[tuple[str, str, datetime | None, str]]:
    """(app_id, symbol, broadcast_at, ixbrl_url) of filings whose file has not been read, newest first."""
    return [
        (r[0], r[1], r[2], r[3])
        for r in conn.execute(
            "SELECT app_id, symbol, broadcast_at, ixbrl_url FROM nse_insider_filing"
            " WHERE detail_at IS NULL AND NOT superseded AND ixbrl_url IS NOT NULL ORDER BY broadcast_at DESC NULLS LAST LIMIT %s",
            (limit,),
        )
    ]


_IX = re.compile(r"<ix:(nonFraction|nonNumeric)\b([^>]*)>(.*?)</ix:\1>", re.S)
_ATTR = {k: re.compile(rf"""{k}=["']([^"']+)["']""") for k in ("name", "contextRef")}


def parse_pit_detail(
    app_id: str, html: bytes, broadcast_at: datetime | None, url: str
) -> list[tuple[Any, ...]]:
    """The disclosures in one filing (a filing can hold several persons), as `store_insider` rows with did '<app_id>:<context>'."""
    facts: dict[
        str, dict[str, str]
    ] = {}  # context -> {field: text}; "MainI" is the company, "DisclosureN" one person's trade
    for m in _IX.finditer(html.decode("utf-8", "replace")):
        n, c = _ATTR["name"].search(m[2]), _ATTR["contextRef"].search(m[2])
        if n and c:
            facts.setdefault(c[1], {})[n[1].split(":")[-1]] = re.sub(r"<[^>]+>", "", m[3]).strip()
    symbol = facts.get("MainI", {}).get("Symbol")
    out = []
    for ctx, f in facts.items():
        if not ctx.startswith("Disclosure"):
            continue
        person = f.get("NameOfThePerson")
        if not person or not symbol:
            continue
        out.append((
            f"{app_id}:{ctx}", symbol, person, _text(f.get("CategoryOfPerson")), _text(f.get("SecuritiesAcquiredOrDisposedTransactionType")),
            _text(f.get("ModeOfAcquisitionOrDisposal")), _text(f.get("TypeOfInstrument")),
            _num(f.get("SecuritiesAcquiredOrDisposedNumberOfSecurity")), _num(f.get("SecuritiesAcquiredOrDisposedValueOfSecurity")),
            _num(f.get("SecuritiesHeldPriorToAcquisitionOrDisposalNumberOfSecurity")), _num(f.get("SecuritiesHeldPriorToAcquisitionOrDisposalPercentageOfShareholding")),
            _num(f.get("SecuritiesHeldPostAcquistionOrDisposalNumberOfSecurity")), _num(f.get("SecuritiesHeldPostAcquistionOrDisposalPercentageOfShareholding")),
            _date(f.get("DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyFromDate")),
            _date(f.get("DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyToDate")),
            _date(f.get("DateOfIntimationToCompany")), broadcast_at, url,
        ))  # fmt: skip
    if not out:
        raise ParseError("no disclosure with a person in the filing")
    return out


def mark_pit_detail(
    conn: psycopg.Connection, app_id: str, now: datetime, error: str | None = None
) -> None:
    conn.execute(
        "UPDATE nse_insider_filing SET detail_at=%s, detail_error=%s WHERE app_id=%s",
        (now, error, app_id),
    )


# ---------------------------------------------------------------- shareholding pattern (headline numbers)


def parse_shareholding(raw: bytes, *, skip_undated: bool = False) -> list[tuple[Any, ...]]:
    """`skip_undated`: drop a filing with no reporting period instead of failing (old history has a few); the daily feed stays strict."""
    out = []
    for r in _json_list(raw):
        try:
            period = _date(r["date"])
            if period is None:
                if skip_undated:
                    continue
                raise ParseError(f"bad period: {r['date']!r}")
            out.append((
                str(r["recordId"]), r["symbol"], _text(r.get("isin")), period,
                _num(r.get("pr_and_prgrp")), _num(r.get("public_val")), _num(r.get("employeeTrusts")),
                _date(r.get("submissionDate")), _ist_to_utc(r.get("broadcastDate")),
                str(r.get("revisedData", "N")).upper() == "Y", _text(r.get("xbrl")),
            ))  # fmt: skip
        except KeyError as e:
            raise ParseError(f"missing {e}") from e
    return out


def store_shareholding(
    conn: psycopg.Connection, rows: Iterable[tuple[Any, ...]], now: datetime
) -> int:
    return _insert(
        conn,
        "INSERT INTO nse_shareholding (record_id, symbol, isin, period_end, promoter_pct, public_pct, employee_trust_pct,"
        " submitted_on, broadcast_at, revised, xbrl_url, ingested_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
        " ON CONFLICT DO NOTHING",
        [(*r, now) for r in rows],
    )


# ---------------------------------------------------------------- shareholding split (FII / DII / MF ...) from the XBRL filing

_XBRL_MEMBERS = {
    "fii_pct": "InstitutionsForeignMember",
    "dii_pct": "InstitutionsDomesticMember",
    "mf_pct": "MutualFundsOrUTIMember",
    "insurance_pct": "InsuranceCompaniesMember",
    "retail_pct": "ResidentIndividualShareholdersHoldingNominalShareCapitalUpToRsTwoLakhMember",
}
_XBRLI, _XBRLDI = "http://www.xbrl.org/2003/instance", "http://xbrl.org/2006/xbrldi"


def parse_shareholding_split(raw: bytes) -> dict[str, Decimal | None]:
    """fii_pct, dii_pct, mf_pct, insurance_pct, retail_pct (percent of all shares) from one SHP filing; a category the company
    does not report is None. Only facts for ONE category on the shareholder-category axis count (not sub-splits)."""
    try:
        root = ET.fromstring(raw)  # noqa: S314
    except ET.ParseError as e:
        raise ParseError(f"bad XBRL: {e}") from e
    member_of: dict[str, str] = {}
    for c in root.iter(f"{{{_XBRLI}}}context"):
        dims = [
            (m.get("dimension", ""), (m.text or "").split(":")[-1])
            for m in c.iter(f"{{{_XBRLDI}}}explicitMember")
        ]
        if len(dims) == 1 and dims[0][0].endswith("CategoryOfShareholdersAxis"):
            member_of[c.get("id", "")] = dims[0][1]
    found: dict[str, Decimal] = {}
    for fact in root:
        if fact.tag.endswith("}ShareholdingAsAPercentageOfTotalNumberOfShares"):
            m, v = member_of.get(fact.get("contextRef", "")), _num(fact.text)
            if m and v is not None:
                found.setdefault(m, v * 100)
    if not found:
        raise ParseError("no shareholder-category facts in the filing")
    return {k: found.get(m) for k, m in _XBRL_MEMBERS.items()}


def pending_splits(conn: psycopg.Connection, limit: int) -> list[tuple[str, str]]:
    """(record_id, xbrl_url) of filings whose XBRL has not been read, newest period first."""
    return [
        (r[0], r[1])
        for r in conn.execute(
            "SELECT record_id, xbrl_url FROM nse_shareholding WHERE split_at IS NULL AND xbrl_url IS NOT NULL"
            " ORDER BY period_end DESC, broadcast_at DESC NULLS LAST LIMIT %s",
            (limit,),
        )
    ]


def store_split(
    conn: psycopg.Connection,
    record_id: str,
    split: dict[str, Decimal | None] | None,
    now: datetime,
    error: str | None = None,
) -> None:
    """Record the XBRL read (or why it failed: the filing is then not retried forever)."""
    s = split or {}
    conn.execute(
        "UPDATE nse_shareholding SET fii_pct=%s, dii_pct=%s, mf_pct=%s, insurance_pct=%s, retail_pct=%s, split_at=%s, split_error=%s WHERE record_id=%s",
        (
            s.get("fii_pct"),
            s.get("dii_pct"),
            s.get("mf_pct"),
            s.get("insurance_pct"),
            s.get("retail_pct"),
            now,
            error,
            record_id,
        ),
    )


def _insert(conn: psycopg.Connection, sql: str, rows: Sequence[tuple[Any, ...]]) -> int:
    """Rows actually inserted (conflicts are not counted)."""
    new = 0
    with conn.cursor() as cur:
        for r in rows:
            cur.execute(sql, r)
            new += cur.rowcount
    return new


# ---------------------------------------------------------------- derived from the daily bars

_DAY = (
    "(SELECT DISTINCT ON (instrument_id) * FROM bar_1d WHERE source='nse'"
    " AND (ts AT TIME ZONE 'Asia/Kolkata')::date=%s ORDER BY instrument_id, dataset_version DESC)"
)
_ORDER = {"value": "close * volume", "volume": "volume"}


def delivery_pct(
    conn: psycopg.Connection, day: date, *, min_volume: int = 0, limit: int = 50
) -> list[tuple[Any, ...]]:
    """(symbol, close, volume, delivery_qty, delivery %) for EQ-series stocks that day, highest delivery % first."""
    return conn.execute(
        f"SELECT i.symbol, b.close, b.volume, b.delivery_qty, round(100 * b.delivery_qty / b.volume, 2) AS pct"  # noqa: S608
        f" FROM {_DAY} b JOIN instrument i USING (instrument_id)"
        " WHERE b.series='EQ' AND b.volume > 0 AND b.delivery_qty IS NOT NULL AND b.volume >= %s"
        " ORDER BY pct DESC, i.symbol LIMIT %s",
        (day, min_volume, limit),
    ).fetchall()


def most_active(
    conn: psycopg.Connection, day: date, *, by: str = "value", limit: int = 20
) -> list[tuple[Any, ...]]:
    """(symbol, close, volume, traded value ~ close x volume) for EQ-series stocks that day; `by` is 'value' or 'volume'."""
    if by not in _ORDER:
        raise ValueError(f"by must be one of {sorted(_ORDER)}")
    return conn.execute(
        f"SELECT i.symbol, b.close, b.volume, b.close * b.volume AS traded_value"  # noqa: S608
        f" FROM {_DAY} b JOIN instrument i USING (instrument_id)"
        f" WHERE b.series='EQ' ORDER BY {_ORDER[by]} DESC, i.symbol LIMIT %s",
        (day, limit),
    ).fetchall()
