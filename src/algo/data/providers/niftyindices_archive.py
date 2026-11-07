"""Rules for capturing NSE Indices' monthly 'Market Capitalisation & Weightage' archive politely and
safely. Pure functions (no network): which months to fetch, what a response means, whether a ZIP is
sound. The script wires them to HTTP."""

from __future__ import annotations

import io
import zipfile
from calendar import monthrange
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
DATASET = "monthly_indices_mcap_weightage"
OK, STOP, RETRY = "ok", "stop", "retry"


def month_range(start: tuple[int, int], end: tuple[int, int]) -> Iterator[tuple[int, int]]:
    """(year, month) from start to end inclusive."""
    y, m = start
    while (y, m) <= end:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def month_label(year: int, month: int) -> str:
    return f"{MONTHS[month - 1]} {year}"  # the form's MonthYear value, e.g. "Mar 2020"


def month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def classify(status: int, content_type: str, body_head: bytes) -> str:
    """STOP on any refusal or challenge (never worked around); RETRY transient trouble; else OK."""
    text = body_head[:4000].decode("utf-8", "ignore").lower()
    if status in (401, 403, 429) or "captcha" in text or "access denied" in text:
        return STOP
    if status >= 500 or status == 408:
        return RETRY
    if status != 200:
        return STOP
    return OK


@dataclass(frozen=True)
class ZipCheck:
    ok: bool
    names: tuple[str, ...]
    reason: str = ""


def check_zip(data: bytes) -> ZipCheck:
    """A ZIP is accepted only if it opens, every member passes its CRC, and it holds PDFs."""
    if not data.startswith(b"PK"):
        return ZipCheck(False, (), "not a zip file")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            bad = z.testzip()
            if bad is not None:
                return ZipCheck(False, (), f"corrupt member {bad}")
            names = tuple(i.filename for i in z.infolist())
    except zipfile.BadZipFile as e:
        return ZipCheck(False, (), f"bad zip: {e}")
    if not any(n.lower().endswith(".pdf") for n in names):
        return ZipCheck(False, names, "no PDFs inside")
    return ZipCheck(True, names)


def backoff_seconds(attempt: int, base: float = 10.0) -> float:
    """Exponential: 10, 20, 40 ... seconds for attempts 1, 2, 3."""
    return float(base * (2 ** (attempt - 1)))
