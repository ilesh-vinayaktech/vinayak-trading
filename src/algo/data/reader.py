"""Read path for bars. Raw prices are never edited; adjustment is applied here, at read time.
  adjust='none'          exactly as traded (execution, audit)
  adjust='split'         split/bonus adjusted (signals, charts); volume scaled inversely
  adjust='total_return'  also folds in cash dividends (performance measurement)
Point in time: with `as_of`, a daily bar is visible only after its session closes + publish lag,
and only corporate actions with knowledge_time <= as_of are applied. as_of=None = hindsight.
Actions the feed could not price (demerger, rights, ...) are returned as `unapplied`;
strict=True refuses to hand back prices they would make wrong."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import psycopg

from algo.core.clock import require_utc
from algo.data.adjust.factors import (
    PRICE_KINDS,
    SPLIT_KINDS,
    ActionRecord,
    Built,
    build_adjustments,
    factor_on,
)
from algo.data.corporate_actions import records_for
from algo.data.issuer_series import Link, chain, stitch

IST = ZoneInfo("Asia/Kolkata")
MODES = ("none", "split", "total_return")


class UnadjustableError(Exception):
    pass


def _version(adjust: str, recs: list[ActionRecord]) -> str:
    """Stable fingerprint of the mode and every action record (incl. verified/provisional state):
    record it with a backtest to pin exactly which adjustments produced its prices."""
    body = [adjust] + sorted(
        json.dumps(
            [str(r.ex_date), r.kind, r.status, str(r.num), str(r.den), str(r.amount), r.provisional]
        )
        for r in recs
    )
    return hashlib.sha256("\n".join(body).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class AdjBar:
    ts: datetime  # bar-open, UTC
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    factor: Decimal  # price factor applied (1 = raw)
    owner: int | None = None  # the instrument that traded and recorded this bar (never merged away)


@dataclass
class History:
    bars: list[AdjBar]
    unapplied: list[ActionRecord] = field(default_factory=list)  # unpriced: prices may be wrong
    provisional: list[ActionRecord] = field(
        default_factory=list
    )  # applied but unverified estimates
    adjustment_version: str = ""  # fingerprint of every input that shaped these prices

    @property
    def clean(self) -> bool:
        """Nothing unpriced and nothing merely estimated affects these prices."""
        return not self.unapplied and not self.provisional


class Loaded:
    """One instrument's raw bars and action records, loaded once. All point-in-time slicing and
    adjustment is then in memory, so a backtest can ask for history thousands of times cheaply."""

    def __init__(
        self,
        rows: list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, Decimal]],
        recs: list[ActionRecord],
        visible_after: timedelta,
        strict: bool,
        owners: list[int] | None = None,
    ) -> None:
        self.rows, self.recs, self.visible_after, self.strict = rows, recs, visible_after, strict
        self.owners = owners if owners is not None else [0] * len(rows)  # 0: owner not tracked
        self.days = [r[0].astimezone(IST).date() for r in rows]
        self._built: dict[str, Built] = {}

    def _build(self, adjust: str) -> Built:
        if adjust not in self._built:
            kinds = (*SPLIT_KINDS, *PRICE_KINDS) + (
                ("dividend",) if adjust == "total_return" else ()
            )
            closes = list(zip(self.days, (r[4] for r in self.rows), strict=True))

            def prev_close_on(ex: date) -> Decimal:
                prior = [c for d, c in closes if d < ex]
                if not prior:
                    raise LookupError(f"no bar before {ex}")
                return Decimal(prior[-1])

            relevant = [r for r in self.recs if r.kind in kinds or r.status == "review"]
            self._built[adjust] = build_adjustments(relevant, prev_close_on)
        return self._built[adjust]

    def history(
        self,
        start: date,
        end: date,
        *,
        adjust: str = "none",
        as_of: datetime | None = None,
    ) -> History:
        if adjust not in MODES:
            raise ValueError(f"adjust must be one of {MODES}")
        as_of = require_utc(as_of) if as_of is not None else None
        idx = [
            i
            for i, (r, d) in enumerate(zip(self.rows, self.days, strict=True))
            if start <= d <= end and (as_of is None or r[0] + self.visible_after <= as_of)
        ]
        if not idx:
            return History([])
        known = [r for r in self.recs if as_of is None or r.knowledge_time <= as_of]
        if adjust == "none":
            raw = [AdjBar(*self.rows[i], Decimal(1), self.owners[i]) for i in idx]
            return History(raw, adjustment_version=_version("none", []))

        built = self._build(adjust)
        first_day = self.days[idx[0]]
        # An unpriced action matters only if a returned bar lies before its ex-date; unpriced
        # dividends matter only for the total-return series.
        unapplied = [
            u
            for u in built.unapplied
            if (as_of is None or u.knowledge_time <= as_of)
            and u.ex_date > first_day
            and (adjust == "total_return" or u.kind != "dividend")
        ]
        provisional = [r for r in known if r.provisional and r.ex_date > first_day]
        if self.strict and unapplied:
            raise UnadjustableError(
                "unpriced corporate actions affect these prices: "
                + ", ".join(f"{u.kind}@{u.ex_date}" for u in unapplied)
            )
        total = adjust == "total_return"
        bars = []
        for i in idx:
            r, d = self.rows[i], self.days[i]
            f = factor_on(built.adjustments, d, total_return=total, as_of=as_of)
            fs = factor_on(built.adjustments, d, volume=True, as_of=as_of)
            bars.append(
                AdjBar(r[0], r[1] * f, r[2] * f, r[3] * f, r[4] * f, r[5] / fs, f, self.owners[i])
            )
        return History(bars, unapplied, provisional, _version(adjust, known))


class BarReader:
    def __init__(
        self,
        conn: psycopg.Connection,
        *,
        source: str = "nse",
        session_length: timedelta = timedelta(hours=6, minutes=15),
        publish_lag: timedelta = timedelta(hours=3),  # bhavcopy appears ~18:30 IST
    ) -> None:
        self.conn, self.source = conn, source
        self.visible_after = session_length + publish_lag

    def _raw(
        self, instrument_id: int
    ) -> list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, Decimal]]:
        return self.conn.execute(
            "SELECT DISTINCT ON (ts) ts,open,high,low,close,volume FROM bar_1d "
            "WHERE instrument_id=%s AND source=%s ORDER BY ts, dataset_version DESC",
            (instrument_id, self.source),
        ).fetchall()

    def load(self, instrument_id: int, *, strict: bool = False) -> Loaded:
        """ONE instrument's own bars and actions (execution, audit). Another ISIN of the same issuer
        is never mixed in: same issuer is not same instrument."""
        rows = self._raw(instrument_id)
        recs = records_for(self.conn, instrument_id, strict=strict)
        return Loaded(rows, recs, self.visible_after, strict, [instrument_id] * len(rows))

    def isin_links(self) -> list[Link]:
        """SAME_ISSUER_ISIN_CHANGE links between instruments (none before migration 024)."""
        table = self.conn.execute("SELECT to_regclass('corporate_action_relationship')").fetchone()
        if table is None or table[0] is None:
            return []
        return [
            Link(*r)
            for r in self.conn.execute(
                "SELECT source_instrument_id, target_instrument_id, effective_date"
                " FROM corporate_action_relationship"
                " WHERE relationship_type='SAME_ISSUER_ISIN_CHANGE'"
                " AND target_instrument_id IS NOT NULL ORDER BY effective_date"
            ).fetchall()
        ]

    def issuer_load(self, instrument_id: int, *, strict: bool = False) -> Loaded:
        """The issuer's continuous series (signals, charts): the ISIN-change chain stitched, each
        bar keeping its owning instrument. Without a link it equals `load`. Data that does not
        match the identity is refused, never guessed."""
        segs = chain(self.isin_links(), instrument_id)
        ids = [g.instrument_id for g in segs]
        rows, owners, recs = stitch(
            segs,
            {i: self._raw(i) for i in ids},
            {i: records_for(self.conn, i, strict=strict) for i in ids},
        )
        return Loaded(rows, recs, self.visible_after, strict, owners)

    def issuer_history(
        self,
        instrument_id: int,
        start: date,
        end: date,
        *,
        adjust: str = "none",
        as_of: datetime | None = None,
        strict: bool = False,
    ) -> History:
        return self.issuer_load(instrument_id, strict=strict).history(
            start, end, adjust=adjust, as_of=as_of
        )

    def history(
        self,
        instrument_id: int,
        start: date,
        end: date,
        *,
        adjust: str = "none",
        as_of: datetime | None = None,
        strict: bool = False,
    ) -> History:
        return self.load(instrument_id, strict=strict).history(
            start, end, adjust=adjust, as_of=as_of
        )
