"""NSE symbolchange.csv (old symbol -> new symbol, effective date) and index constituent lists."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import UTC, date, datetime

from algo.data.providers.base import ParseError


@dataclass(frozen=True)
class SymbolChange:
    old: str
    new: str
    effective: date  # first day the NEW symbol is used


@dataclass(frozen=True)
class IndexMember:
    symbol: str
    isin: str
    industry: str


def _rows(raw: bytes, required: set[str]) -> list[dict[str, str]]:
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        reader.fieldnames = [h.strip() for h in reader.fieldnames or []]
        missing = required - set(reader.fieldnames)
        if missing:
            raise ParseError(f"missing columns {sorted(missing)}")
        return [{k: (v or "").strip() for k, v in r.items()} for r in reader]
    except (UnicodeDecodeError, csv.Error) as e:
        raise ParseError(str(e)) from e


def parse_symbol_changes(raw: bytes) -> list[SymbolChange]:
    try:
        return [
            SymbolChange(
                r["OLD SYMBOL"],
                r["NEW SYMBOL"],
                datetime.strptime(r["EFFECTIVE DATE"], "%d-%b-%Y").replace(tzinfo=UTC).date(),
            )  # fmt: skip
            for r in _rows(raw, {"OLD SYMBOL", "NEW SYMBOL", "EFFECTIVE DATE"})
        ]
    except ValueError as e:
        raise ParseError(str(e)) from e


def parse_index_list(raw: bytes) -> list[IndexMember]:
    return [
        IndexMember(r["Symbol"], r["ISIN Code"], r["Industry"])
        for r in _rows(raw, {"Symbol", "ISIN Code", "Industry"})
    ]
