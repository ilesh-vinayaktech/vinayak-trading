"""NSE corporates-corporateActions JSON -> typed actions. `subject` is free text; anything the
parser cannot price exactly is status='review' (never silently adjusted).
Conventions (NSE): Bonus A:B = A new shares per B held => share multiplier (A+B)/B.
Split/consolidation 'From Rs X To Rs Y' => multiplier X/Y. Rights/demerger/arrangement/buy-back and
percent-of-face-value dividends need data this feed lacks => review.
Verify multipliers against the price gap at ex-date once historical bars are loaded."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from algo.data.providers.base import ParseError

MAIN_SERIES = frozenset({"EQ", "BE", "BZ"})
_SPLIT = re.compile(r"\bto\b")
_SEP = re.compile(r"\s*/(?!-)\s*|\s+and\s+|\s*&\s*", re.I)
_RATIO = re.compile(r"(\d+)\s*:\s*(\d+)")
_FV = re.compile(r"r[se]\.?\s*(\d+(?:\.\d+)?)\D*?to\s*r[se]\.?\s*(\d+(?:\.\d+)?)", re.I)
_AMT = re.compile(r"r[se]\.?\s*-?\s*(\d+(?:,\d{3})*(?:\.\d+)?)", re.I)
_BARE_DIV = re.compile(r"\bdiv\w*\s*-?\s*(\d+(?:\.\d+)?)(?=\s*(?:per\b|$))", re.I)  # Div-17.50
_NOISE = re.compile(
    r"^[\W_]*$|^per sh|\b(agm|egm|meeting|genaral|generalmeeting|book closure|bc (end )?dates?"
    r"|e-?voting|election|elctn|elec\b|registrar|transfer agent|purpose revised|revised)\b"
    r"|^an+[au]+l"
)
_PCT = re.compile(r"\d+(?:\.\d+)?\s*%")
_REVIEW_WORDS = (
    "demerger", "arrangement", "arangement", "sch of", "amalgamation", "merger", "spin",
    "reduction", "buy",
)  # fmt: skip


@dataclass(frozen=True)
class Component:
    kind: str  # bonus | split | dividend | rights | demerger | other ...
    status: str  # ok | review
    num: Decimal | None = None  # share multiplier = num/den (bonus, split)
    den: Decimal | None = None
    amount: Decimal | None = None  # cash per share (dividend) or premium (rights)
    reason: str = ""


@dataclass(frozen=True)
class CorporateAction:
    symbol: str
    isin: str | None
    ex_date: date
    record_date: date | None
    idx: int  # component index within the NSE row
    comp: Component
    subject: str


def _review(kind: str, reason: str, **kw: Decimal | None) -> Component:
    return Component(kind, "review", reason=reason, **kw)


def parse_component(text: str) -> Component | None:
    t = " ".join(text.lower().split())
    if not t:
        return None
    if t.startswith("distribut"):
        return _review("distribution", "unit distribution (non-equity)")
    m = re.search(r"\bbon(?:us)?\s*-?\s*(\d+)\s*:\s*(\d+)", t)
    if m:
        a, b = Decimal(m[1]), Decimal(m[2])
        if b == 0:
            return _review("bonus", "zero denominator")
        return Component("bonus", "ok", a + b, b)
    # "Spl" is ambiguous in NSE shorthand (split vs SPECIAL dividend): it only counts as a split
    # when it carries a face-value pair. Unambiguous split words without one go to review.
    f = _FV.search(t)
    unambiguous = re.search(r"split|splt|sub-division|consolidation|\bfv\b", t)
    if f and (unambiguous or re.search(r"\bspl\b", t)):
        if Decimal(f[2]) == 0:
            return _review("split", "zero face value")
        return Component("split", "ok", Decimal(f[1]), Decimal(f[2]))
    if unambiguous:
        return _review("split", "face values not found")
    if re.match(r"(rights?|rhts?|rhs)\b", t):
        r, amt = _RATIO.search(t), _AMT.search(t)
        return _review(
            "rights", "subscription price needs historic face value",
            num=Decimal(r[1]) if r else None, den=Decimal(r[2]) if r else None,
            amount=Decimal(amt[1].replace(",", "")) if amt else None,
        )  # fmt: skip
    for w in _REVIEW_WORDS:
        if w in t:
            return _review(w.strip(), "no ratio/price in feed; manual treatment")
    if "div" in t or "special" in t:
        amts = [Decimal(a.replace(",", "")) for a in _AMT.findall(t)]
        if not amts and (bare := _BARE_DIV.search(t)):
            amts = [Decimal(bare[1])]
        if not amts:
            if _PCT.search(t):
                return _review("dividend", "percent of face value; historic face value unknown")
            return _review("dividend", "no rupee amount")
        return Component("dividend", "ok", amount=sum(amts, Decimal(0)))
    if _NOISE.search(t):
        return None  # meeting / book-closure / notice text: no economic action
    return _review("other", "unrecognised subject")


def parse_subject(subject: str) -> list[Component]:
    return [c for part in _SEP.split(subject) if (c := parse_component(part)) is not None]


def _date(v: str) -> date | None:
    if v in ("", "-", None):
        return None
    return datetime.strptime(v, "%d-%b-%Y").replace(tzinfo=UTC).date()


def parse_actions(raw: bytes) -> tuple[list[CorporateAction], list[str]]:
    """Returns (actions, skipped) - skipped = human-readable reasons for dropped rows."""
    try:
        rows = json.loads(raw)
        if not isinstance(rows, list):
            raise ParseError("expected a JSON list")
        out, skipped = [], []
        for r in rows:
            sym, subj = r["symbol"], r["subject"].strip()
            if r.get("series") not in MAIN_SERIES:
                skipped.append(f"{sym}: series {r.get('series')}")
                continue
            ex = _date(r["exDate"])
            if ex is None:
                skipped.append(f"{sym}: no ex-date ({subj})")
                continue
            for i, c in enumerate(parse_subject(subj)):
                out.append(CorporateAction(sym, r.get("isin"), ex, _date(r.get("recDate", "-")),
                                           i, c, subj))  # fmt: skip
        return out, skipped
    except (KeyError, ValueError, InvalidOperation, TypeError) as e:
        raise ParseError(str(e)) from e
