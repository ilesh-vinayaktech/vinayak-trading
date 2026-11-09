"""NSE Indices press releases -> structured rows. Stages 1 and 2 only: this module EXTRACTS what a
release says (sections, excluded/included symbols, dates, with page + raw text) and CLASSIFIES the
document. It does not decide what changes Nifty 200; that is the derivation stage.

Anything it cannot place is returned as an explicit classification (MANUAL_REVIEW), not guessed."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime

PARSER_VERSION = (
    "7"  # 2: wrapped dates; 3: sub-headings; 4: classification; 5: lettered; 6: "... Index";
    # 7: index table continued on the next page; "(Symbol: X) shall be excluded from the following"
)

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
_SECTION = re.compile(r"^\s*(\d+|[A-Za-z])\)\s+(\S.*?)\s*$", re.M)


def section_number(label: str) -> int:
    """'3' -> 3; a lettered heading 'b' -> 102 (offset so it never collides with a numbered one)."""
    return int(label) if label.isdigit() else 100 + ord(label.lower()) - 96


_ACTION = re.compile(
    r"(?:companies|company|stocks?)\s+(?:is|are)\s+being\s+(excluded|included)", re.I
)
_SUBHEAD = re.compile(r"^\s*(NIFTY[\w &\-]*?)\s*\((?:to be )?renamed", re.I)
_ROW = re.compile(r"^\s*(\d+)\s+(\S.*?)\s{2,}([A-Z0-9][A-Z0-9&\-_.]*)\s*$", re.M)
_NOTICE_INDEX = re.compile(r"^\s*(\d+)\s+(Nifty\S*\s.+?)\s*$", re.M | re.I)
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


PARSED = "PARSED"
MANUAL = "MANUAL_REVIEW_REQUIRED"
NOT_RELEVANT = "NOT_RELEVANT"
UNSUPPORTED = "UNSUPPORTED_FORMAT"

_COMPONENT_MENTION = re.compile(
    r"nifty\s*(?:50|next\s*50|100|200|midcap\s*100|(?:free\s*float|full)\s*midcap\s*100)\b", re.I
)
_ACTION_WORDS = re.compile(
    r"\b(?:exclu\w*|inclu\w*|replac\w*|defer\w*|null and void|reconstitut\w*|dummy)", re.I
)
_BOILERPLATE = re.compile(r"About (?:National Stock Exchange|NSE Indices)", re.I)


def classify_unparsed(pages: list[str]) -> tuple[str, str]:
    """(classification, reason) for a release that produced no rows. A document is NOT_RELEVANT only
    if it says nothing about changing a Nifty 200 component index; else a person must read it."""
    text = "\n".join(pages)
    if len(text.strip()) < 40:
        return UNSUPPORTED, "no text layer (scanned image): needs OCR or manual reading"
    body = _BOILERPLATE.split(text)[0]  # the 'About' footer names Nifty 50 in every release
    comp, act = _COMPONENT_MENTION.search(body), _ACTION_WORDS.search(body)
    if comp and act:
        return MANUAL, f"mentions '{act.group(0)}' and '{comp.group(0)}' but has no parsable tables"
    return NOT_RELEVANT, "no constituent action on a Nifty 200 component index"


@dataclass(frozen=True)
class Release:
    announced: date
    kind: str
    rows: tuple[Row, ...]
    sections: tuple[str, ...]  # every section name seen (components or not)
    effective_dates: tuple[date, ...]
    notes: tuple[str, ...] = field(default=())
    classification: str = PARSED
    classification_reason: str = ""
    extracted_text: str | None = None  # kept only when a person must read it

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
    return COMPONENTS.get(re.sub(r"INDEX$", "", key))  # 2017-18 headings read "NIFTY 50 Index"


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
        for line_m in re.finditer(r"^.*$", body, re.M):
            line = line_m.group(0)
            sub = _SUBHEAD.match(line)
            if sub:  # one numbered section can hold several indices, each under its own sub-heading
                name = sub.group(1).strip()
                action = None
                continue
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
                    page=text.count("\f", 0, off) + 1, section_no=section_number(s.group(1)),
                    section_name=name, component=canon(name), action=action,
                    symbol=r.group(3), company=r.group(2).strip(),
                    effective_from=effective_at(s.start()), raw_text=line.strip(),
                ))  # fmt: skip
    rows += _following_rows(text, effective_at)
    names = tuple(s.group(2).strip() for s in sections)
    if rows:
        return Release(
            announced, KIND_REPLACEMENT_TABLES, tuple(rows), names, eff_all, tuple(notes)
        )
    notice = _notice_rows(text, announced, eff_marks)
    if notice:
        return Release(announced, KIND_COMPANY_NOTICE, tuple(notice), names, eff_all, tuple(notes))
    label, why = classify_unparsed(pages)
    keep = text if label in (MANUAL, UNSUPPORTED) else None
    return Release(announced, KIND_NO_STRUCTURE, (), names, eff_all, tuple(notes), label, why, keep)


_DECIDED = re.compile(
    r"decided\s+to\s+exclude\s+(.+?)\s+from\s+(?:various|the)\s+indices", re.I | re.S
)
_INDEX_TABLES = re.compile(r"Sr\.\s*No\.\s+Index\s+Name", re.I)
_DUMMY_TOKEN = re.compile(r"\bDUMMY[A-Z0-9]+\b")


_FOLLOWING = re.compile(
    r"\(Symbol:\s*([A-Z0-9][A-Z0-9&\-_.]*)\)\s+shall\s+be\s+excluded\s+from\s+the\s+following"
    r"\s+indices",
    re.I,
)
_FOLLOWING_SECTION = 200  # offset so these rows never collide with a numbered table section


def _one_table(text: str) -> bool:
    """Exactly one 'Index Name' table. A header repeated as the first line of a later page is the
    same table continuing, not a second one."""
    heads = list(_INDEX_TABLES.finditer(text))
    return bool(heads) and all(
        i == 0 or not text[text.rfind("\f", 0, h.start()) + 1 : h.start()].strip()
        for i, h in enumerate(heads)
    )


def _following_rows(text: str, effective_at: Callable[[int], date | None]) -> list[Row]:
    """'... (Symbol: X) shall be excluded from the following indices:' then a numbered list of
    index names. Read next to any replacement tables in the same release."""
    out: list[Row] = []
    for m in _FOLLOWING.finditer(text):
        for line in text[m.end() :].splitlines()[1:]:
            n = _NOTICE_INDEX.match(line)
            if n:
                out.append(Row(
                    page=text.count("\f", 0, m.start()) + 1,
                    section_no=_FOLLOWING_SECTION + int(n.group(1)),
                    section_name=n.group(2).strip(), component=canon(n.group(2)),
                    action="EXCLUDED", symbol=m.group(1), company="",
                    effective_from=effective_at(m.start()), raw_text=line.strip(),
                ))  # fmt: skip
            elif line.strip() and not _INDEX_TABLES.search(line):
                break
    return out


def _notice_rows(text: str, announced: date, eff_marks: list[tuple[int, date]]) -> list[Row]:
    """Single-company corporate-action notices. Deliberately strict: exactly one decision
    sentence (or one dummy symbol) and exactly one 'Index Name' table, otherwise nothing is
    returned and the document stays MANUAL_REVIEW."""
    idx = list(_NOTICE_INDEX.finditer(text))
    if not idx or not eff_marks or not _one_table(text):
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
