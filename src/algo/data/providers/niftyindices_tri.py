"""NSE Indices 'Total Returns Index' history endpoint: request building, response parsing and the
hash that identifies the DATA (not the response).

Contract (read from the site's scripts, then exercised): POST /BackPage/getTotalReturnIndexString
with a JSON body whose `cinfo` field is the string
    {'name':'NIFTY 200','startDate':'31-Oct-2025','endDate':'30-Oct-2026','indexName':'Nifty 200'}
The reply is a JSON array, newest first: Index Name, Date ('30 Oct 2026'), TotalReturnsIndex
('17750.88', the gross total-return level), NTR_Value ('-' when no net series exists) and a
per-response RequestNumber that is ignored everywhere."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from algo.data.providers.niftyindices_archive import MONTHS

ENDPOINT = "https://www.niftyindices.com/BackPage/getTotalReturnIndexString"
ENDPOINT_VERSION = "2026-11"  # bump when the observed contract changes
PARSER_VERSION = "1"
MAX_DAYS = 365  # the page's own limit; the server does not enforce it, we comply anyway
_MONTH = {m: i + 1 for i, m in enumerate(MONTHS)}
_DATE = re.compile(r"^(\d{1,2}) ([A-Z][a-z]{2}) (\d{4})$")
_LEVEL = re.compile(r"^\d+(?:\.\d+)?$")


class TriError(Exception):
    pass


@dataclass(frozen=True)
class Observation:
    day: date
    level: Decimal
    net_level: Decimal | None  # NTR_Value, None when the endpoint says '-'


def windows(start: date, end: date, max_days: int = MAX_DAYS) -> list[tuple[date, date]]:
    """Consecutive, NON-overlapping windows of at most `max_days` days covering [start, end]."""
    if end < start:
        raise ValueError("end before start")
    out, s = [], start
    while s <= end:
        e = min(s + timedelta(days=max_days - 1), end)
        out.append((s, e))
        s = e + timedelta(days=1)
    return out


def fmt_date(d: date) -> str:
    return f"{d.day:02d}-{MONTHS[d.month - 1]}-{d.year}"  # locale-independent 'dd-Mon-yyyy'


def request_body(index_name: str, start: date, end: date) -> bytes:
    cinfo = (
        f"{{'name':'{index_name.upper()}','startDate':'{fmt_date(start)}',"
        f"'endDate':'{fmt_date(end)}','indexName':'{index_name}'}}"
    )
    return json.dumps({"cinfo": cinfo}).encode()


def parse_date(s: str) -> date:
    m = _DATE.match(s.strip())
    if not m or m.group(2) not in _MONTH:
        raise TriError(f"malformed date {s!r}")
    try:
        return date(int(m.group(3)), _MONTH[m.group(2)], int(m.group(1)))
    except ValueError as e:
        raise TriError(f"impossible date {s!r}") from e


def _level(v: object, what: str) -> Decimal:
    if not isinstance(v, str) or not _LEVEL.match(v.strip()):
        raise TriError(f"malformed {what} {v!r}")
    try:
        return Decimal(v.strip())
    except InvalidOperation as e:  # pragma: no cover - guarded by the regex
        raise TriError(f"malformed {what} {v!r}") from e


def parse_response(raw: bytes) -> list[Observation]:
    """Every row must be well formed or the whole response is refused (nothing is skipped)."""
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError as e:
        raise TriError(f"not JSON: {e}") from e
    if not isinstance(rows, list):
        raise TriError("expected a JSON array")
    out = []
    for r in rows:
        if not isinstance(r, dict) or not {"Date", "TotalReturnsIndex"} <= r.keys():
            raise TriError(f"row without Date / TotalReturnsIndex: {r!r}")
        ntr = r.get("NTR_Value", "-")
        net = None if ntr in ("-", "", None) else _level(ntr, "NTR_Value")
        out.append(Observation(parse_date(r["Date"]), _level(r["TotalReturnsIndex"], "level"), net))
    return out


def normalized_hash(observations: list[Observation]) -> str:
    """Identifies the DATA: dates and levels only, in date order. Excludes the per-response request
    number, the index-name casing and the ordering of the reply."""
    h = hashlib.sha256()
    for o in sorted(observations, key=lambda x: x.day):
        h.update(f"{o.day}|{o.level}|{'' if o.net_level is None else o.net_level}\n".encode())
    return h.hexdigest()
