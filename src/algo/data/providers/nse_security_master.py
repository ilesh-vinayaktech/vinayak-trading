"""NSE EQUITY_L.csv security master (symbol, name, series, listing date, lot, ISIN)."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from algo.data.providers.base import ParseError

URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
REQUIRED = {"SYMBOL", "NAME OF COMPANY", "SERIES", "DATE OF LISTING", "MARKET LOT", "ISIN NUMBER"}


@dataclass(frozen=True)
class Security:
    symbol: str
    name: str
    series: str
    listed_on: date
    lot_size: Decimal
    isin: str


def parse_security_master(raw: bytes) -> list[Security]:
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8")))
        reader.fieldnames = [h.strip() for h in reader.fieldnames or []]
        missing = REQUIRED - set(reader.fieldnames)
        if missing:
            raise ParseError(f"missing columns {sorted(missing)}")
        out = []
        for row in reader:
            r = {k: (v or "").strip() for k, v in row.items()}
            listed = datetime.strptime(r["DATE OF LISTING"], "%d-%b-%Y").replace(tzinfo=UTC)
            out.append(Security(r["SYMBOL"], r["NAME OF COMPANY"], r["SERIES"], listed.date(),
                                Decimal(r["MARKET LOT"]), r["ISIN NUMBER"]))  # fmt: skip
        return out
    except (UnicodeDecodeError, ValueError, InvalidOperation, csv.Error) as e:
        raise ParseError(str(e)) from e
