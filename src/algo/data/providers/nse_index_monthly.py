"""NSE Indices' monthly 'Constituents of <index>' PDFs (month-end membership, with prices, index
market cap and weights) -> structured rows.

The PDFs lay out each constituent over several lines, so rows are rebuilt from word COORDINATES
(`pdftotext -bbox-layout`): every word belongs to the nearest symbol by vertical position, and the
columns are split by x. Nothing is guessed: a snapshot carries `problems` (wrong record shape,
duplicate symbols, weights not summing to ~100) for a person to look at."""

from __future__ import annotations

import html
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from algo.data.providers.nse_index_releases import canon, parse_date

PARSER_VERSION = "2"  # 2: numbers only right of the Close Price header
Word = tuple[float, float, float, float, str]  # x0, y0, x1, y1, text

_WORD = re.compile(
    r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>'
)
_NUM = re.compile(r"^\d[\d,]*(?:\.\d+)?$")
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9&\-]*$")
_TITLE = re.compile(r"Constituents of\s+(.+?)\s*$", re.I)
_MAX_GAP = 14.0  # a word further than this from every symbol line is not part of a record
WEIGHT_SUM = (Decimal("99.5"), Decimal("100.5"))


@dataclass(frozen=True)
class Constituent:
    symbol: str
    name: str
    industry: str
    price: Decimal
    index_mcap: Decimal
    weight: Decimal
    page: int


@dataclass(frozen=True)
class IndexSnapshot:
    index_name: str  # as printed, e.g. "NIFTY Midcap 100"
    component: str | None  # canonical Nifty 200 component, None for other indices
    as_of: date
    rows: tuple[Constituent, ...]
    problems: tuple[str, ...] = field(default=())


def extract_words(pdf: bytes) -> list[list[Word]]:
    """Words with coordinates for each page (poppler's pdftotext -bbox-layout)."""
    out = subprocess.run(
        ["pdftotext", "-bbox-layout", "-", "-"], input=pdf, capture_output=True, check=True
    ).stdout.decode("utf-8", "replace")
    pages = re.findall(r"<page[^>]*>(.*?)</page>", out, flags=re.S)
    return [
        [
            (float(a), float(b), float(c), float(d), html.unescape(w))
            for a, b, c, d, w in _WORD.findall(p)
        ]
        for p in pages
    ]


def _title_and_date(pages: list[list[Word]]) -> tuple[str, date]:
    first = sorted(pages[0], key=lambda w: (round(w[1]), w[0]))
    lines: dict[int, list[str]] = {}
    for _, y, _, _, w in first:
        lines.setdefault(round(y), []).append(w)
    text = [" ".join(ws) for _, ws in sorted(lines.items())]
    title = next((m.group(1) for ln in text if (m := _TITLE.search(ln))), "")
    when = next((ln for ln in text if re.fullmatch(r"[A-Z][a-z]+ \d{1,2}, \d{4}", ln.strip())), "")
    if not title or not when:
        raise ValueError("not a constituents report: title or date not found")
    return title, parse_date(when)


def _dec(s: str) -> Decimal:
    try:
        return Decimal(s.replace(",", ""))
    except InvalidOperation as e:  # pragma: no cover - guarded by _NUM
        raise ValueError(s) from e


def parse_snapshot(pages: list[list[Word]]) -> IndexSnapshot:
    title, as_of = _title_and_date(pages)
    rows: list[Constituent] = []
    problems: list[str] = []
    for pno, ws in enumerate(pages, 1):
        header = [w for w in ws if w[4] in ("Weightage", "(%)")]
        top = max((w[3] for w in header), default=0.0)
        body = [w for w in ws if w[1] > top]
        if not body:
            continue
        name_h = next((w for w in ws if w[4] == "Security"), None)
        ind_h = next((w for w in ws if w[4] == "Industry"), None)
        edge = (name_h[0] + ind_h[0]) / 2 + 10 if name_h and ind_h else 225.0
        close_h = next((w for w in ws if w[4] == "Close"), None)
        num_from = close_h[0] if close_h else edge + 100  # numbers only right of 'Close Price'

        left = min(w[0] for w in body)
        anchors = [w for w in body if w[0] < left + 40 and _SYMBOL.match(w[4])]
        members: dict[Word, list[Word]] = {a: [] for a in anchors}
        for w in body:
            if w in members:
                continue
            near = min(anchors, key=lambda a: abs(a[1] - w[1]), default=None)
            if near is not None and abs(near[1] - w[1]) <= _MAX_GAP:
                members[near].append(w)
        for a, rest in members.items():
            nums = sorted(
                (w for w in rest if _NUM.match(w[4]) and w[0] >= num_from), key=lambda w: w[0]
            )
            text = [w for w in rest if w not in nums]
            if len(nums) != 3:
                problems.append(
                    f"page {pno} {a[4]}: expected price, mcap, weight; got {len(nums)} numbers"
                )
                continue
            name = " ".join(
                w[4] for w in sorted(text, key=lambda w: (round(w[1]), w[0])) if w[0] < edge
            )
            industry = " ".join(w[4] for w in sorted(text, key=lambda w: w[0]) if w[0] >= edge)
            price, mcap, weight = (_dec(n[4]) for n in nums)
            rows.append(Constituent(a[4], name, industry, price, mcap, weight, pno))
    seen: set[str] = set()
    for r in rows:
        if r.symbol in seen:
            problems.append(f"duplicate symbol {r.symbol}")
        seen.add(r.symbol)
    total = sum((r.weight for r in rows), Decimal(0))
    if rows and not WEIGHT_SUM[0] <= total <= WEIGHT_SUM[1]:
        problems.append(f"weights sum to {total}, not ~100")
    if not rows:
        problems.append("no constituents found")
    return IndexSnapshot(title, canon(title), as_of, tuple(rows), tuple(problems))
