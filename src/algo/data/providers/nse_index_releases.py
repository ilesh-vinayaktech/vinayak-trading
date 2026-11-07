"""NSE Indices press releases -> structured rows. Stages 1 and 2 only: this module EXTRACTS what a
release says (sections, excluded/included symbols, dates, with page + raw text) and CLASSIFIES the
document. It does not decide what changes Nifty 200; that is the derivation stage.

Anything it cannot place is returned as an explicit classification (MANUAL_REVIEW), not guessed."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime

PARSER_VERSION = "2"  # 2: dates wrapped across lines ("March\n31, 2022") are read

# Component indices of Nifty 200 (= Nifty 100 + Midcap 100; Nifty 100 = Nifty 50 + Next 50).
COMPONENTS = {
    "NIFTY50": "NIFTY_50",
    "NIFTYNEXT50": "NIFTY_NEXT_50",
    "NIFTY100": "NIFTY_100",
    "NIFTY200": "NIFTY_200",
    "NIFTYMIDCAP100": "MIDCAP_100",
    "NIFTYFREEFLOATMIDCAP100": "MIDCAP_100_FREE_FLOAT",
    "NIFTYFULLMIDCAP100": "MIDCAP_100_FULL",
}

KIND_REPLACEMENT_TABLES = "REPLACEMENT_TABLES"  # numbered sections with excluded/included tables
KIND_COMPANY_NOTICE = "COMPANY_NOTICE"  # one corporate action, one table of affected index names
KIND_NO_STRUCTURE = "MANUAL_REVIEW"  # nothing we can place (incl. scanned images)

_DATE = r"([A-Z][a-z]+\.?\s+\d{1,2},?\s+\d{4})"
_EFFECTIVE = re.compile(r"(?:effective\s+(?:from\s+)?|w\.e\.f\.?\s+)" + _DATE)
_HEADER_DATE = re.compile(r"Mumbai[,:]?\s+" + _DATE)
_SECTION = re.compile(r"^\s*(\d+)\)\s+(\S.*?)\s*$", re.M)
_ACTION = re.compile(
    r"(?:companies|company|stocks?)\s+(?:is|are)\s+being\s+(excluded|included)", re.I
)
_ROW = re.compile(r"^\s*(\d+)\s+(\S.*?)\s{2,}([A-Z0-9][A-Z0-9&\-_.]*)\s*$", re.M)
_NOTICE_INDEX = re.compile(r"^\s*(\d+)\s+(Nifty\s.+?)\s*$", re.M | re.I)
_SYMBOL_IN_PARENS = re.compile(r"\(([A-Z0-9][A-Z0-9&\-_.]*)\)")


@dataclass(frozen=True)
class Row:
    page: int  # 1-based
    section_no: int
    section_name: str  # as printed
    component: str | None  # canonical component index, None = not a Nifty 200 component
    action: str  # EXCLUDED | INCLUDED
    symbol: str
    company: str
    effective_from: date | None
    raw_text: str
    related_symbol: str | None = None  # e.g. the dummy symbol this listing replaces


@dataclass(frozen=True)
class Release:
    announced: date
    kind: str
    rows: tuple[Row, ...]
    sections: tuple[str, ...]  # every section name seen (components or not)
    effective_dates: tuple[date, ...]
    notes: tuple[str, ...] = field(default=())

    @property
    def component_rows(self) -> tuple[Row, ...]:
        return tuple(r for r in self.rows if r.component)


def extract_pages(pdf: bytes) -> list[str]:
    """Text of each page (poppler's pdftotext, layout preserved)."""
    out = subprocess.run(
        ["pdftotext", "-layout", "-", "-"], input=pdf, capture_output=True, check=True
    ).stdout.decode("utf-8", "replace")
    pages = out.split("\f")
    return pages[:-1] if len(pages) > 1 and not pages[-1].strip() else pages


def parse_date(s: str) -> date:
    s = " ".join(s.replace(".", "").replace(",", "").split())
    for fmt in ("%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(s, fmt).date()  # noqa: DTZ007 - calendar date, no time
        except ValueError:
            continue
    raise ValueError(f"unparseable date {s!r}")


def canon(name: str) -> str | None:
    key = re.sub(r"[^A-Z0-9]", "", name.upper())
    return COMPONENTS.get(key)


def parse_release(pages: list[str], announced: date) -> Release:
    text = "\f".join(pages)
    notes: list[str] = []
    m = _HEADER_DATE.search(text)
    if m and parse_date(m.group(1)) != announced:
        notes.append(f"header date {parse_date(m.group(1))} differs from listed date {announced}")
    eff_marks = [(m.start(), parse_date(m.group(1))) for m in _EFFECTIVE.finditer(text)]
    eff_all = tuple(sorted({d for _, d in eff_marks}))

    def effective_at(offset: int) -> date | None:
        before = [d for o, d in eff_marks if o <= offset]
        return before[-1] if before else (eff_marks[0][1] if eff_marks else None)

    sections = list(_SECTION.finditer(text))
    rows: list[Row] = []
    for i, s in enumerate(sections):
        end = sections[i + 1].start() if i + 1 < len(sections) else len(text)
        body = text[s.end() : end]
        name = s.group(2).strip()
        action = None
        pos = 0
        for line_m in re.finditer(r"^.*$", body, re.M):
            line = line_m.group(0)
            a = _ACTION.search(line)
            if a:
                action = a.group(1).upper()
                continue
            if re.search(r"No\s+(?:inclusion|exclusion)\s+is\s+being", line, re.I):
                action = None
                continue
            r = _ROW.match(line)
            if r and action:
                off = s.end() + line_m.start()
                rows.append(Row(
                    page=text.count("\f", 0, off) + 1, section_no=int(s.group(1)),
                    section_name=name, component=canon(name), action=action,
                    symbol=r.group(3), company=r.group(2).strip(),
                    effective_from=effective_at(s.start()), raw_text=line.strip(),
                ))  # fmt: skip
            pos = line_m.end()
        del pos
    names = tuple(s.group(2).strip() for s in sections)
    if rows:
        return Release(
            announced, KIND_REPLACEMENT_TABLES, tuple(rows), names, eff_all, tuple(notes)
        )
    notice = _notice_rows(text, announced, eff_marks)
    if notice:
        return Release(announced, KIND_COMPANY_NOTICE, tuple(notice), names, eff_all, tuple(notes))
    return Release(announced, KIND_NO_STRUCTURE, (), names, eff_all, tuple(notes))


_DECIDED = re.compile(
    r"decided\s+to\s+exclude\s+(.+?)\s+from\s+(?:various|the)\s+indices", re.I | re.S
)
_INDEX_TABLES = re.compile(r"Sr\.\s*No\.\s+Index\s+Name", re.I)
_DUMMY_TOKEN = re.compile(r"\bDUMMY[A-Z0-9]+\b")


def _notice_rows(text: str, announced: date, eff_marks: list[tuple[int, date]]) -> list[Row]:
    """Single-company corporate-action notices. Deliberately strict: exactly one decision
    sentence (or one dummy symbol) and exactly one 'Index Name' table, otherwise nothing is
    returned and the document stays MANUAL_REVIEW."""
    idx = list(_NOTICE_INDEX.finditer(text))
    if not idx or not eff_marks or len(_INDEX_TABLES.findall(text)) != 1:
        return []
    dummies = sorted(set(_DUMMY_TOKEN.findall(text)))
    decided = _DECIDED.findall(text)
    if decided:  # exclusion of a (post-demerger) listing
        if len(decided) != 1 or len(dummies) > 1:
            return []
        symbols = _SYMBOL_IN_PARENS.findall(decided[0]) or re.findall(
            r"\b[A-Z][A-Z0-9&\-_.]{1,}\b", decided[0]
        )
        if not symbols:
            return []
        related = dummies[0] if dummies else None
        eff = [d for o, d in eff_marks if o > _DECIDED.search(text).start()]  # type: ignore[union-attr]
        if not eff:
            return []
        action, effective = "EXCLUDED", eff[0]
    elif len(dummies) == 1 and re.search(r"shall\s+be\s+included", text, re.I):
        symbols, related, action, effective = dummies, None, "INCLUDED", eff_marks[0][1]
    else:
        return []
    return [
        Row(
            page=text.count("\f", 0, m.start()) + 1, section_no=int(m.group(1)),
            section_name=m.group(2).strip(), component=canon(m.group(2)), action=action,
            symbol=sym, company="", effective_from=effective, raw_text=m.group(0).strip(),
            related_symbol=related,
        )
        for sym in symbols
        for m in idx
    ]  # fmt: skip
