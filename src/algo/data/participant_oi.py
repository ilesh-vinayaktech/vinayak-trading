# ruff: noqa: E501
"""FII open interest in index futures from NSE's participant-wise open interest file (one CSV a day, history back years): parse, store, and the date range to fetch.
The file: a title line, a header line, then one row per client type (Client, DII, FII, Pro, TOTAL); we keep FII "Future Index Long" and "Future Index Short"."""

from __future__ import annotations

import csv
import io
import re
from datetime import UTC, date, datetime

import psycopg

URL = "https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{day:%d%m%Y}.csv"
WARM = "https://www.nseindia.com/all-reports-derivatives"


def _count(v: str) -> int:
    """A contract count; some files write "80,776.00"."""
    return round(float(v.replace(",", "")))


def parse(raw: bytes, asked: date | None = None) -> tuple[date, int, int]:
    """(day, FII index futures long, short) from one file. The day is the one in the title line; some years have no title line, then `asked` (the day we requested) is used.
    Raises ValueError when the file is not what we expect."""
    lines = raw.decode("utf-8-sig").splitlines()
    start = next((k for k, ln in enumerate(lines) if ln.startswith("Client Type")), None)
    if start is None:
        raise ValueError("participant OI file: no header line")
    day = asked
    m = re.search(r"as on ([A-Za-z]+) (\d{1,2}), (\d{4})", lines[0]) if start > 0 else None
    if m is not None:  # newer files say "Nov", older ones "June"
        day = (
            datetime.strptime(f"{m.group(1)[:3]} {m.group(2)} {m.group(3)}", "%b %d %Y")
            .replace(tzinfo=UTC)
            .date()
        )
    if day is None:
        raise ValueError("participant OI file: no date in the title line")
    for row in csv.DictReader(io.StringIO("\n".join(lines[start:]))):
        fields = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        if fields.get("Client Type") == "FII":
            return day, _count(fields["Future Index Long"]), _count(fields["Future Index Short"])
    raise ValueError("participant OI file: no FII row")


def store(conn: psycopg.Connection, day: date, long_oi: int, short_oi: int, now: datetime) -> bool:
    """Insert one day; False when it was already stored (a published day does not change)."""
    cur = conn.execute(
        "INSERT INTO fii_index_futures_oi (day, long_oi, short_oi, ingested_at) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
        (day, long_oi, short_oi, now),
    )
    return cur.rowcount == 1


def stored_days(conn: psycopg.Connection, start: date, end: date) -> set[date]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT day FROM fii_index_futures_oi WHERE day BETWEEN %s AND %s", (start, end)
        )
    }
