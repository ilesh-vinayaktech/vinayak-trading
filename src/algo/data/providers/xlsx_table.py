"""Minimal, dependency-free reader for the first sheet of an .xlsx file, used when an exchange
publishes a table as a spreadsheet although the URL says CSV. Cell text is taken as stored in the
XML, with ONE normalisation: a spreadsheet stores numbers as binary doubles, so 277.90 can be
stored as '277.89999999999998'. A number with more than 15 significant digits is a double artefact
(Excel itself shows 15) and is replaced by the shortest decimal that round-trips to the same double
('277.9'). Shorter numbers are kept verbatim ('108.10'). The raw file is never modified; this only
reads it. Inputs are untrusted: sizes are capped and only the two parts needed are opened."""

from __future__ import annotations

import csv
import io
import re
import zipfile
from xml.etree import ElementTree as ET

from algo.data.providers.base import ParseError

MAX_PART_BYTES = 64 * 1024 * 1024
MAGIC = b"PK\x03\x04"
_CELL = re.compile(r"^([A-Z]+)(\d+)$")


def is_xlsx(raw: bytes) -> bool:
    return raw[:4] == MAGIC


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _read(z: zipfile.ZipFile, name: str) -> bytes:
    info = z.getinfo(name)
    if info.file_size > MAX_PART_BYTES:
        raise ParseError(f"{name}: {info.file_size} bytes exceeds the {MAX_PART_BYTES} cap")
    return z.read(name)


def _number(text: str) -> str:
    """Undo the binary-double artefact of a spreadsheet number (see the module docstring)."""
    digits = text.lstrip("-").replace(".", "")
    if len(digits) <= 15 or "e" in text.lower():
        return text
    try:
        short = repr(float(text))
    except ValueError:
        return text
    return text if "e" in short else short


def _col(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def _shared_strings(xml: bytes) -> list[str]:
    out = []
    for si in ET.fromstring(xml):
        out.append("".join(t.text or "" for t in si.iter() if _local(t.tag) == "t"))
    return out


def xlsx_rows(raw: bytes) -> list[list[str]]:
    """Rows of the first worksheet as strings; missing cells are ''."""
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        names = set(z.namelist())
        sheet = "xl/worksheets/sheet1.xml"
        if sheet not in names:
            raise ParseError("no xl/worksheets/sheet1.xml")
        shared = (
            _shared_strings(_read(z, "xl/sharedStrings.xml"))
            if ("xl/sharedStrings.xml" in names)
            else []
        )
        root = ET.fromstring(_read(z, sheet))
    except (zipfile.BadZipFile, ET.ParseError, KeyError) as e:
        raise ParseError(f"not a readable xlsx: {e}") from e
    rows: list[list[str]] = []
    for row in root.iter():
        if _local(row.tag) != "row":
            continue
        cells: dict[int, str] = {}
        for c in row:
            if _local(c.tag) != "c":
                continue
            m = _CELL.match(c.get("r", ""))
            if not m:
                raise ParseError(f"cell without a reference: {c.attrib}")
            kind = c.get("t")
            if kind == "inlineStr":
                text = "".join(t.text or "" for t in c.iter() if _local(t.tag) == "t")
            else:
                v = next((x.text or "" for x in c if _local(x.tag) == "v"), "")
                if kind == "s":
                    try:
                        text = shared[int(v)]
                    except (ValueError, IndexError) as e:
                        raise ParseError(f"bad shared string index {v!r}") from e
                else:
                    text = _number(v) if kind in (None, "n") else v
            cells[_col(m.group(1))] = text
        width = max(cells) + 1 if cells else 0
        rows.append([cells.get(i, "") for i in range(width)])
    return rows


def xlsx_to_csv(raw: bytes) -> bytes:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(xlsx_rows(raw))
    return buf.getvalue().encode("utf-8")
