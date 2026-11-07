"""NSE's legacy daily bhavcopy archive (cmDDMONYYYYbhav.csv.zip), the exchange's own end-of-day
file for dates before the sec_bhavdata_full format. Used as INDEPENDENT evidence that the exchange
traded on a date (the file's TIMESTAMP column) and, through PREVCLOSE, that a session sits between
two others. It says nothing about the purpose of a session or its hours."""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from algo.data.providers.base import ParseError
from algo.data.providers.niftyindices_archive import MONTHS

URL = "https://nsearchives.nseindia.com/content/historical/EQUITIES/{y}/{mon}/cm{dd}{mon}{y}bhav.csv.zip"
MAX_BYTES = 64 * 1024 * 1024


def url(d: date) -> str:
    return URL.format(y=d.year, mon=MONTHS[d.month - 1].upper(), dd=f"{d.day:02d}")


@dataclass(frozen=True)
class LegacyBhav:
    days: frozenset[date]  # every TIMESTAMP in the file
    rows: int
    close: dict[tuple[str, str], Decimal]  # (symbol, series) -> CLOSE
    prev_close: dict[tuple[str, str], Decimal]  # (symbol, series) -> PREVCLOSE
    duplicates: int = 0  # rows whose (symbol, series) already appeared in the file


def _day(text: str) -> date:
    parts = text.strip().split("-")
    mon = [m.upper() for m in MONTHS]
    if len(parts) != 3 or parts[1].upper() not in mon:
        raise ParseError(f"malformed TIMESTAMP {text!r}")
    try:
        return date(int(parts[2]), mon.index(parts[1].upper()) + 1, int(parts[0]))
    except ValueError as e:
        raise ParseError(f"impossible TIMESTAMP {text!r}") from e


def parse(raw: bytes) -> LegacyBhav:
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        names = z.namelist()
        if len(names) != 1:
            raise ParseError(f"expected one file in the archive, found {len(names)}")
        if z.getinfo(names[0]).file_size > MAX_BYTES:
            raise ParseError("archive member too large")
        text = z.read(names[0]).decode("utf-8")
    except (zipfile.BadZipFile, UnicodeDecodeError) as e:
        raise ParseError(f"not a readable bhavcopy archive: {e}") from e
    reader = csv.DictReader(io.StringIO(text))
    fields = {(h or "").strip() for h in reader.fieldnames or []}
    need = {"SYMBOL", "SERIES", "CLOSE", "PREVCLOSE", "TIMESTAMP"}
    if not need <= fields:
        raise ParseError(f"missing columns {sorted(need - fields)}")
    days: set[date] = set()
    close, prev = {}, {}
    n = dup = 0
    for r in reader:
        r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
        key = (r["SYMBOL"], r["SERIES"])
        dup += key in close
        try:
            close[key], prev[key] = Decimal(r["CLOSE"]), Decimal(r["PREVCLOSE"])
        except InvalidOperation as e:
            raise ParseError(f"non-numeric price for {key}") from e
        days.add(_day(r["TIMESTAMP"]))
        n += 1
    if n == 0:
        raise ParseError("no rows")
    return LegacyBhav(frozenset(days), n, close, prev, dup)


def chain(
    earlier_close: dict[tuple[str, str], Decimal], later_prev: dict[tuple[str, str], Decimal]
) -> tuple[int, int]:
    """(symbols in both files, of which the later PREVCLOSE equals the earlier CLOSE)."""
    both = earlier_close.keys() & later_prev.keys()
    return len(both), sum(earlier_close[k] == later_prev[k] for k in both)
