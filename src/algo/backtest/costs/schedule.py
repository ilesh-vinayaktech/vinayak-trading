"""Effective-dated trading-cost schedules, as DATA (JSON files in config/cost_schedules/), never as
constants in code. Every component cites a source (url + sha256 of the stored document + quote);
a schedule is `verified` only when a named person has checked it against those sources.

status:  verified              checked by a person against the cited documents
         extracted_unverified  read from the documents but not yet verified by a person
         assumed_backfill      a CURRENT rate extended into a period it is not evidenced for
                               (explicit, opt-in, flagged on every run that uses it)
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

STATUSES = ("verified", "extracted_unverified", "assumed_backfill")
ROUNDINGS = ("HALF_UP_2DP", "NONE")
TYPES = (
    "BROKERAGE", "STT", "EXCHANGE_TRANSACTION", "SEBI_TURNOVER", "STAMP_DUTY", "DP_CHARGE", "GST",
)  # fmt: skip


class Basis(StrEnum):
    TRADE_VALUE = "TRADE_VALUE"  # rate_pct of qty * price
    PER_EXECUTED_ORDER = "PER_EXECUTED_ORDER"  # flat amount for each executed order
    PER_SCRIP = "PER_SCRIP"  # flat amount per scrip (here: per order of that scrip)
    GST_BASE = "GST_BASE"  # rate_pct of the sum of the GST-taxable components


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    BOTH = "BOTH"


class ScheduleError(Exception):
    pass


class NoScheduleForDate(ScheduleError):
    pass


@dataclass(frozen=True)
class Source:
    key: str
    url: str
    retrieved_at: str
    sha256: str
    quote: str  # a literal substring of the stored document
    locator: str = ""  # where in the document (table / row / section), for the human verifier


@dataclass(frozen=True)
class Component:
    type: str
    basis: Basis
    side: Side
    rate_pct: Decimal | None  # percent of the basis value (0.015 = 0.015%)
    amount: Decimal | None  # flat rupees (PER_* bases)
    minimum: Decimal | None
    maximum: Decimal | None
    taxable_for_gst: bool
    gst_inclusive: bool  # the published amount already includes GST (e.g. the DP charge)
    rounding: str
    source: str  # key into Schedule.sources


@dataclass(frozen=True)
class Schedule:
    id: str
    version: str
    name: str
    broker: str
    exchange: str
    segment: str
    instrument_type: str
    product: str  # DELIVERY | INTRADAY
    valid_from: date
    valid_until: date | None  # inclusive; None = open-ended
    currency: str
    status: str
    verified_by: str | None
    verified_at: datetime | None
    notes: str
    contract_note_min_brokerage: Decimal | None
    components: tuple[Component, ...]
    sources: Mapping[str, Source]
    doc_hash: str  # sha256 of the canonical JSON this schedule was loaded from
    assumptions: tuple[
        str, ...
    ] = ()  # what this schedule takes on trust; a verifier must accept each by name

    def covers(self, day: date) -> bool:
        return self.valid_from <= day and (self.valid_until is None or day <= self.valid_until)


def _dec(v: Any, field: str) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except Exception as e:
        raise ScheduleError(f"{field}: not a number: {v!r}") from e


def _date(v: Any, field: str) -> date | None:
    if v is None:
        return None
    try:
        return date.fromisoformat(v)
    except (TypeError, ValueError) as e:
        raise ScheduleError(f"{field}: not an ISO date: {v!r}") from e


def _component(d: Mapping[str, Any], sources: Mapping[str, Source], where: str) -> Component:
    try:
        basis, side = Basis(d["basis"]), Side(d["side"])
    except (KeyError, ValueError) as e:
        raise ScheduleError(f"{where}: bad basis/side: {e}") from e
    c = Component(
        type=d.get("type", ""),
        basis=basis,
        side=side,
        rate_pct=_dec(d.get("rate_pct"), f"{where}.rate_pct"),
        amount=_dec(d.get("amount"), f"{where}.amount"),
        minimum=_dec(d.get("minimum"), f"{where}.minimum"),
        maximum=_dec(d.get("maximum"), f"{where}.maximum"),
        taxable_for_gst=bool(d.get("taxable_for_gst", False)),
        gst_inclusive=bool(d.get("gst_inclusive", False)),
        rounding=d.get("rounding", ""),
        source=d.get("source", ""),
    )
    if c.type not in TYPES:
        raise ScheduleError(f"{where}: unknown component type {c.type!r}")
    if c.rounding not in ROUNDINGS:
        raise ScheduleError(f"{where}: unknown rounding {c.rounding!r}")
    if c.source not in sources:
        raise ScheduleError(f"{where}: cites unknown source {c.source!r}")
    percent = basis in (Basis.TRADE_VALUE, Basis.GST_BASE)
    if percent and (c.rate_pct is None or c.rate_pct < 0):
        raise ScheduleError(f"{where}: {basis} needs rate_pct >= 0")
    if not percent and (c.amount is None or c.amount < 0):
        raise ScheduleError(f"{where}: {basis} needs amount >= 0")
    for name, v in (("minimum", c.minimum), ("maximum", c.maximum)):
        if v is not None and v < 0:
            raise ScheduleError(f"{where}: {name} cannot be negative")
    if c.minimum is not None and c.maximum is not None and c.minimum > c.maximum:
        raise ScheduleError(f"{where}: minimum above maximum")
    if (basis is Basis.GST_BASE) != (c.type == "GST"):
        raise ScheduleError(f"{where}: GST must be the (only) GST_BASE component")
    if c.taxable_for_gst and c.gst_inclusive:
        raise ScheduleError(f"{where}: cannot be both GST-taxable and GST-inclusive")
    return c


def schedule_from_dict(d: Mapping[str, Any]) -> Schedule:
    where = d.get("id", "<schedule>")
    raw_sources = d.get("sources") or {}
    sources = {}
    for key, s in raw_sources.items():
        for f in ("url", "retrieved_at", "sha256", "quote"):
            if not s.get(f):
                raise ScheduleError(f"{where}: source {key!r} is missing {f}")
        sources[key] = Source(
            key, s["url"], s["retrieved_at"], s["sha256"], s["quote"], s.get("locator", "")
        )
    comps = tuple(
        _component(c, sources, f"{where}.components[{i}]")
        for i, c in enumerate(d.get("components") or [])
    )
    if not comps:
        raise ScheduleError(f"{where}: no components")
    if sum(1 for c in comps if c.type == "GST") > 1:
        raise ScheduleError(f"{where}: more than one GST component")
    if comps[-1].type != "GST" and any(c.type == "GST" for c in comps):
        raise ScheduleError(f"{where}: GST must be the last component")
    status = d.get("status", "")
    if status not in STATUSES:
        raise ScheduleError(f"{where}: unknown status {status!r}")
    verified_at = d.get("verified_at")
    if status == "verified" and not (d.get("verified_by") and verified_at):
        raise ScheduleError(f"{where}: verified needs verified_by and verified_at")
    vf, vu = (
        _date(d.get("valid_from"), f"{where}.valid_from"),
        _date(d.get("valid_until"), f"{where}.valid_until"),
    )
    if vf is None or (vu is not None and vu < vf):
        raise ScheduleError(f"{where}: bad validity range")
    for f in (
        "id",
        "version",
        "name",
        "broker",
        "exchange",
        "segment",
        "instrument_type",
        "product",
    ):
        if not d.get(f):
            raise ScheduleError(f"{where}: missing {f}")
    if d["product"] not in ("DELIVERY", "INTRADAY"):
        raise ScheduleError(f"{where}: unknown product {d['product']!r}")
    assumptions = d.get("assumptions", [])
    if not isinstance(assumptions, list) or not all(
        isinstance(a, str) and a.strip() for a in assumptions
    ):
        raise ScheduleError(f"{where}: assumptions must be a list of non-empty statements")
    canonical = json.dumps(d, sort_keys=True, separators=(",", ":"), default=str)
    return Schedule(
        id=d["id"],
        version=d["version"],
        name=d["name"],
        broker=d["broker"],
        exchange=d["exchange"],
        segment=d["segment"],
        instrument_type=d["instrument_type"],
        product=d["product"],
        valid_from=vf,
        valid_until=vu,
        currency=d.get("currency", "INR"),
        status=status,
        verified_by=d.get("verified_by"),
        verified_at=datetime.fromisoformat(verified_at) if verified_at else None,
        notes=d.get("notes", ""),
        contract_note_min_brokerage=_dec(d.get("contract_note_min_brokerage"), f"{where}.min"),
        components=comps,
        sources=sources,
        doc_hash=hashlib.sha256(canonical.encode()).hexdigest(),
        assumptions=tuple(assumptions),
    )


def load_schedules(directory: Path, *, pattern: str = "*.json") -> list[Schedule]:
    out = []
    for f in sorted(directory.glob(pattern)):
        doc = json.loads(f.read_text())
        for entry in doc["schedules"] if "schedules" in doc else [doc]:
            out.append(schedule_from_dict(entry))
    return out


class ScheduleBook:
    """The set of schedules a run may use; picks the one in force on a trade date."""

    def __init__(
        self, schedules: Iterable[Schedule], *, allowed_statuses: Iterable[str] = ("verified",)
    ):
        self.allowed = tuple(allowed_statuses)
        self.schedules = sorted(
            (s for s in schedules if s.status in self.allowed),
            key=lambda s: (s.product, s.valid_from),
        )
        for a, b in zip(self.schedules, self.schedules[1:], strict=False):
            if a.product == b.product and (a.valid_until is None or a.valid_until >= b.valid_from):
                raise ScheduleError(f"schedules {a.id} and {b.id} overlap for {a.product}")

    def for_date(self, day: date, product: str = "DELIVERY") -> Schedule:
        for s in self.schedules:
            if s.product == product and s.covers(day):
                return s
        raise NoScheduleForDate(
            f"no {product} cost schedule (statuses allowed: {', '.join(self.allowed)}) covers {day}"
        )

    def coverage(self, product: str = "DELIVERY") -> list[tuple[date, date | None]]:
        return [(s.valid_from, s.valid_until) for s in self.schedules if s.product == product]
