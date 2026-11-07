"""NSE EOD bhavcopy (sec_bhavdata_full CSV), main-board series EQ/BE/BZ.
Verified against real files (Nov 2026): symbols are unique per day across all series, so a stock
moving EQ->BE keeps one continuous history. SME (SM/ST), bonds (GS/GB), InvIT/REIT are skipped."""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from algo.core.calendar import SessionCalendar
from algo.data.bars import Bar, Freq
from algo.data.providers.base import NotPublishedError, ParseError
from algo.data.providers.xlsx_table import is_xlsx, xlsx_to_csv

URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"
SERIES = frozenset({"EQ", "BE", "BZ"})
REQUIRED = {"SYMBOL", "SERIES", "DATE1", "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "CLOSE_PRICE",
            "TTL_TRD_QNTY"}  # fmt: skip


def _dec(v: str) -> Decimal:
    return Decimal(v.strip())


def _opt(v: str | None) -> Decimal | None:
    return None if v in (None, "", "-") else _dec(v)


def _text(raw: bytes) -> str:
    """The file as CSV text. NSE has served a spreadsheet (.xlsx bytes) under the CSV URL; its cells
    are read exactly as stored. The raw bytes in the lake are never altered."""
    return (xlsx_to_csv(raw) if is_xlsx(raw) else raw).decode("utf-8")


def file_date(raw: bytes) -> date | None:
    """The single trading date a bhavcopy file actually holds (its DATE1 column), or None when the
    file is empty, has no such column or mixes dates. NSE re-serves the last session's file on
    holidays, and a Muhurat session's data can appear in the NEXT holiday's file."""
    try:
        reader = csv.DictReader(io.StringIO(_text(raw)))
        reader.fieldnames = [h.strip() for h in reader.fieldnames or []]
        days = {
            datetime.strptime((r.get("DATE1") or "").strip(), "%d-%b-%Y").replace(tzinfo=UTC).date()
            for r in reader
        }
    except (UnicodeDecodeError, ValueError, csv.Error, ParseError):
        return None
    return days.pop() if len(days) == 1 else None


class NseBhavcopy:
    name = "nse"

    def __init__(self, http_get: Callable[[str], bytes], calendar: SessionCalendar) -> None:
        self._get = http_get  # injected: all NSE HTTP lives behind one client
        self.calendar = calendar

    def supports_corrections(self) -> bool:
        return False

    def freq(self, dataset: str) -> Freq:
        return Freq.D1

    def url(self, dataset: str, d: date) -> str:
        return URL.format(ddmmyyyy=d.strftime("%d%m%Y"))

    def fetch(self, dataset: str, d: date) -> bytes:
        return self._get(self.url(dataset, d))

    def parse(self, dataset: str, d: date, raw: bytes) -> Iterable[Bar]:
        try:
            reader = csv.DictReader(io.StringIO(_text(raw)))
            reader.fieldnames = [h.strip() for h in reader.fieldnames or []]
            missing = REQUIRED - set(reader.fieldnames)
            if missing:
                raise ParseError(f"missing columns {sorted(missing)}")
            out = []
            for row in reader:
                row = {k: (v or "").strip() for k, v in row.items()}
                if row["SERIES"] not in SERIES:
                    continue
                day = datetime.strptime(row["DATE1"], "%d-%b-%Y").replace(tzinfo=UTC).date()
                if day < d:  # holiday: NSE re-serves the previous trading day's file
                    raise NotPublishedError(f"file holds {day}, not {d}")
                if day != d:
                    raise ParseError(f"row date {day} != partition {d}")
                session = self.calendar.session(d)
                if session is None:  # data dated on a day the calendar calls closed
                    raise ParseError(f"{d} is not a trading day per calendar")
                out.append(Bar(
                    row["SYMBOL"], session[0], _dec(row["OPEN_PRICE"]), _dec(row["HIGH_PRICE"]),
                    _dec(row["LOW_PRICE"]), _dec(row["CLOSE_PRICE"]), _dec(row["TTL_TRD_QNTY"]),
                    {"series": row["SERIES"], "prev_close": _opt(row.get("PREV_CLOSE")),
                     "delivery_qty": _opt(row.get("DELIV_QTY"))},
                ))  # fmt: skip
            return out
        except (UnicodeDecodeError, ValueError, InvalidOperation, csv.Error) as e:
            raise ParseError(str(e)) from e
