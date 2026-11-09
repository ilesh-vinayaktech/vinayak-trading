"""Manual-review workflow for corporate actions the NSE feed cannot price (demerger, rights,
arrangement, buy-back, ...). A person resolves each item with explicit inputs; the decision is
stored in action_resolution (never in the derived corporate_action table), applied by the reader
as a price-only factor, and must be confirmed before strict (live-trading) reads rely on it."""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

import psycopg
from psycopg.types.json import Jsonb

from algo.core.clock import require_utc
from algo.data.adjust.factors import demerger_factor, rights_factor

WARN_TOLERANCE = Decimal("0.25")  # factor vs the actual ex-date price move
MIN_PEERS = 30  # Nifty 200 peers needed to estimate the market move for method "gap"


class ResolveError(Exception):
    pass


@dataclass(frozen=True)
class Resolution:
    treatment: str
    factor: Decimal | None
    method: str
    status: str  # provisional | verified | no_adjustment_verified | ignored_with_reason | rejected
    verified_by: str | None
    source_url: str | None
    note: str


@dataclass(frozen=True)
class ReviewItem:
    instrument_id: int
    symbol: str
    ex_date: date
    kind: str
    subjects: list[str]
    reasons: list[str]
    prev_close: Decimal | None  # raw close of the session before ex_date
    ex_close: Decimal | None  # raw close on/after ex_date
    resolution: Resolution | None

    @property
    def observed_ratio(self) -> Decimal | None:
        """What the market actually did across the ex-date (includes ordinary price noise)."""
        if self.prev_close and self.ex_close:
            return self.ex_close / self.prev_close
        return None


@dataclass(frozen=True)
class Resolved:
    factor: Decimal | None
    warning: str | None


_QUEUE = """
SELECT c.instrument_id, a.source_symbol, c.ex_date, c.kind,
       array_agg(DISTINCT c.subject), array_agg(DISTINCT c.reason),
       pb.close, xb.close, r.treatment, r.factor, r.method, r.status, r.confirmed_by,
       r.source_url, r.note
FROM corporate_action c
JOIN instrument_alias a ON a.instrument_id=c.instrument_id AND a.source='nse' AND a.valid_to IS NULL
LEFT JOIN LATERAL (SELECT close FROM bar_1d b WHERE b.instrument_id=c.instrument_id
    AND (b.ts AT TIME ZONE 'Asia/Kolkata')::date < c.ex_date
    ORDER BY b.ts DESC, b.dataset_version DESC LIMIT 1) pb ON true
LEFT JOIN LATERAL (SELECT close FROM bar_1d b WHERE b.instrument_id=c.instrument_id
    AND (b.ts AT TIME ZONE 'Asia/Kolkata')::date >= c.ex_date
    ORDER BY b.ts, b.dataset_version DESC LIMIT 1) xb ON true
LEFT JOIN LATERAL (SELECT * FROM action_resolution r WHERE r.instrument_id=c.instrument_id
    AND r.ex_date=c.ex_date AND r.kind=c.kind ORDER BY r.id DESC LIMIT 1) r ON true
WHERE c.status='review'
GROUP BY c.instrument_id, a.source_symbol, c.ex_date, c.kind, pb.close, xb.close,
         r.treatment, r.factor, r.method, r.status, r.confirmed_by, r.source_url, r.note
ORDER BY c.ex_date, a.source_symbol, c.kind
"""


def evidence_class(status: str | None, method: str | None) -> str:
    """How strong the evidence behind an action's latest resolution is. Both a gap estimate and an
    exchange-derived factor can be PROVISIONAL; they must never be reported as equivalent."""
    if status is None:
        return "UNRESOLVED"
    if status == "provisional":
        if method == "gap":
            return "PROVISIONAL_GAP_ESTIMATE"
        if method == "exchange_adjusted_price":
            return "PROVISIONAL_EXCHANGE_DERIVED"
        return "PROVISIONAL_FROM_TERMS"
    return status.upper()


def review_queue(
    conn: psycopg.Connection,
    *,
    kinds: list[str] | None = None,
    symbols: list[str] | None = None,
    include_resolved: bool = False,
) -> list[ReviewItem]:
    out = []
    for row in conn.execute(_QUEUE):
        (
            iid,
            sym,
            ex,
            kind,
            subjects,
            reasons,
            prev,
            exc,
            treatment,
            factor,
            method,
            status,
            by,
            url,
            note,
        ) = row
        if (kinds and kind not in kinds) or (symbols and sym not in symbols):
            continue
        res = Resolution(treatment, factor, method, status, by, url, note) if treatment else None
        if res is not None and not include_resolved:
            continue
        out.append(
            ReviewItem(iid, sym, ex, kind, sorted(subjects), sorted(reasons), prev, exc, res)
        )
    return out


def _instrument(conn: psycopg.Connection, symbol: str) -> int:
    row = conn.execute(
        "SELECT instrument_id FROM instrument_alias WHERE source='nse' AND source_symbol=%s "
        "AND valid_to IS NULL",
        (symbol,),
    ).fetchone()
    if row is None:
        raise ResolveError(f"unknown symbol {symbol}")
    return int(row[0])


def _prev_close(conn: psycopg.Connection, iid: int, ex: date) -> Decimal:
    row = conn.execute(
        "SELECT close FROM bar_1d WHERE instrument_id=%s "
        "AND (ts AT TIME ZONE 'Asia/Kolkata')::date < %s "
        "ORDER BY ts DESC, dataset_version DESC LIMIT 1",
        (iid, ex),
    ).fetchone()
    if row is None:
        raise ResolveError(f"no bar before {ex}: cannot price this action")
    return Decimal(row[0])


def _need(params: dict[str, Decimal], *names: str) -> list[Decimal]:
    for n in names:
        if n not in params:
            raise ResolveError(f"missing parameter {n}")
    return [params[n] for n in names]


def resolve(
    conn: psycopg.Connection,
    *,
    symbol: str,
    ex_date: date,
    kind: str,
    method: str,
    note: str,
    by: str,
    now: datetime,
    params: dict[str, Decimal] | None = None,
    min_peers: int = MIN_PEERS,
    status: str | None = None,
    source_type: str | None = None,
    source_url: str | None = None,
    source_hash: str | None = None,
) -> Resolved:
    """method: ignore | direct{factor} | demerger{child_per_parent, child_price} |
    rights{new, held, subscription_price} | exchange_adjusted_price{base_price} (the exchange's
    ex-date reference price: preferred evidence for a demerger) | cost_allocation{parent_share} |
    gap (no params: the stock's actual ex-date price ratio
    divided by the median move of its Nifty 200 peers; an approximation for when the entitlement
    ratio is unknown). Computes the price factor for bars before ex_date,
    stores it (append-only, unconfirmed) and warns if it is far from the actual price move."""
    params = params or {}
    iid = _instrument(conn, symbol)
    exists = conn.execute(
        "SELECT 1 FROM corporate_action WHERE instrument_id=%s AND ex_date=%s AND kind=%s "
        "AND status='review' LIMIT 1",
        (iid, ex_date, kind),
    ).fetchone()
    if exists is None:
        raise ResolveError(f"no review action {kind} for {symbol} on {ex_date}")
    inputs: dict[str, str] = {k: str(v) for k, v in params.items()}
    factor: Decimal | None
    try:
        if method == "ignore":
            factor = None
        elif method == "direct":
            (factor,) = _need(params, "factor")
            if factor <= 0:
                raise ResolveError("factor must be positive")
        elif method == "demerger":
            ratio, price = _need(params, "child_per_parent", "child_price")
            prev = _prev_close(conn, iid, ex_date)
            inputs["parent_prev_close"] = str(prev)
            factor = demerger_factor(ratio, price, prev)
        elif method == "rights":
            new, held, sub = _need(params, "new", "held", "subscription_price")
            prev = _prev_close(conn, iid, ex_date)
            inputs["prev_close"] = str(prev)
            factor = rights_factor(new, held, sub, prev)
        elif method == "exchange_adjusted_price":
            (base,) = _need(params, "base_price")
            prev = _prev_close(conn, iid, ex_date)
            if not 0 < base < prev:
                raise ResolveError("base_price must be positive and below the previous close")
            inputs["prev_close"] = str(prev)
            factor = base / prev
        elif method == "cost_allocation":
            (share,) = _need(params, "parent_share")
            if not 0 < share <= 1:
                raise ResolveError("parent_share must be in (0, 1]")
            factor = share
        elif method == "gap":
            factor, gap_inputs = _gap_factor(conn, iid, ex_date, min_peers)
            inputs.update(gap_inputs)
        else:
            raise ResolveError(f"unknown method {method}")
    except ValueError as e:  # from the pure factor maths
        raise ResolveError(str(e)) from e
    allowed = (
        ("ignored_with_reason", "no_adjustment_verified", "rejected")
        if factor is None
        else ("provisional", "verified")
    )
    status = status or allowed[0]
    if status not in allowed:
        kind_txt = "no-adjustment" if factor is None else "factor"
        raise ResolveError(f"status {status} is not valid for a {kind_txt} resolution")
    verifying = status in ("verified", "no_adjustment_verified")
    if verifying:
        if method == "gap":
            raise ResolveError(
                "a gap estimate cannot be verified: use an exact method with a source"
            )
        _need_source(source_type, source_url)
    conn.execute(
        "INSERT INTO action_resolution (instrument_id,ex_date,kind,treatment,factor,method,inputs,"
        "note,resolved_by,resolved_at,status,source_type,source_url,source_hash,confirmed_by,"
        "confirmed_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (iid, ex_date, kind, "ignore" if factor is None else "factor", factor, method,
         Jsonb(json.loads(json.dumps(inputs))), note, by, require_utc(now), status, source_type,
         source_url, source_hash, by if verifying else None,
         require_utc(now) if verifying else None),
    )  # fmt: skip
    if method == "gap":
        return Resolved(
            factor,
            "approximate: market-adjusted observed gap (~1-2% error); "
            "replace with method=demerger once the entitlement ratio is known",
        )
    return Resolved(factor, _warn(conn, iid, ex_date, factor))


_SESSIONS = """
SELECT (SELECT (ts AT TIME ZONE 'Asia/Kolkata')::date FROM bar_1d WHERE instrument_id=%(i)s
          AND (ts AT TIME ZONE 'Asia/Kolkata')::date < %(ex)s ORDER BY ts DESC LIMIT 1),
       (SELECT (ts AT TIME ZONE 'Asia/Kolkata')::date FROM bar_1d WHERE instrument_id=%(i)s
          AND (ts AT TIME ZONE 'Asia/Kolkata')::date >= %(ex)s ORDER BY ts LIMIT 1)
"""
_PEERS = """
SELECT b1.close / b0.close
FROM index_snapshot s
JOIN bar_1d b0 ON b0.instrument_id=s.instrument_id
  AND (b0.ts AT TIME ZONE 'Asia/Kolkata')::date=%(d0)s
JOIN bar_1d b1 ON b1.instrument_id=s.instrument_id
  AND (b1.ts AT TIME ZONE 'Asia/Kolkata')::date=%(d1)s
WHERE s.index_id='NIFTY200' AND s.instrument_id<>%(i)s
  AND NOT EXISTS (SELECT 1 FROM corporate_action c WHERE c.instrument_id=s.instrument_id
                  AND c.ex_date > %(d0)s AND c.ex_date <= %(d1)s)
"""


def _gap_factor(
    conn: psycopg.Connection, iid: int, ex: date, min_peers: int
) -> tuple[Decimal, dict[str, str]]:
    d0, d1 = conn.execute(_SESSIONS, {"i": iid, "ex": ex}).fetchone() or (None, None)
    if d0 is None or d1 is None:
        raise ResolveError(f"no bar on both sides of {ex}: cannot measure the gap")
    own = conn.execute(
        "SELECT (SELECT close FROM bar_1d WHERE instrument_id=%s AND (ts AT TIME ZONE "
        "'Asia/Kolkata')::date=%s ORDER BY dataset_version DESC LIMIT 1), "
        "(SELECT close FROM bar_1d "
        "WHERE instrument_id=%s AND (ts AT TIME ZONE 'Asia/Kolkata')::date=%s ORDER BY "
        "dataset_version DESC LIMIT 1)",
        (iid, d0, iid, d1),
    ).fetchone()
    assert own is not None
    observed = Decimal(own[1]) / Decimal(own[0])
    ratios = [Decimal(r[0]) for r in conn.execute(_PEERS, {"d0": d0, "d1": d1, "i": iid})]
    n = len(ratios)
    if n < min_peers:
        raise ResolveError(f"only {n} peers with clean prices on {d1}; need {min_peers}")
    market = statistics.median(ratios)  # exact Decimal arithmetic (SQL percentile_cont is float)
    factor = observed / market
    if not 0 < factor < 1:
        raise ResolveError(
            f"no price drop to explain (observed {observed:.4f}, market {market:.4f})"
        )
    return factor, {"observed": str(observed), "market_median": str(market), "peers": str(n)}


def _warn(conn: psycopg.Connection, iid: int, ex: date, factor: Decimal | None) -> str | None:
    if factor is None:
        return None
    row = conn.execute(
        "SELECT (SELECT close FROM bar_1d WHERE instrument_id=%s AND (ts AT TIME ZONE "
        "'Asia/Kolkata')::date < %s ORDER BY ts DESC LIMIT 1), (SELECT close FROM bar_1d WHERE "
        "instrument_id=%s AND (ts AT TIME ZONE 'Asia/Kolkata')::date >= %s ORDER BY ts LIMIT 1)",
        (iid, ex, iid, ex),
    ).fetchone()
    if row is None or row[0] is None or row[1] is None:
        return None
    observed = Decimal(row[1]) / Decimal(row[0])
    if abs(observed / factor - 1) > WARN_TOLERANCE:
        return f"factor {factor:.4f} differs from the observed ex-date move {observed:.4f}"
    return None


def _need_source(source_type: str | None, source_url: str | None) -> None:
    if not source_type or not source_url:
        raise ResolveError("verification needs a source (source_type and source_url)")


def verify(
    conn: psycopg.Connection,
    *,
    symbol: str,
    ex_date: date,
    kind: str,
    by: str,
    now: datetime,
    source_type: str,
    source_url: str,
    source_hash: str | None = None,
) -> None:
    """Promote the latest resolution to verified / no_adjustment_verified, citing the authority
    (company filing, exchange notice). Appends a new row, so the earlier state stays as audit.
    Estimates made with method=gap can never be verified: re-resolve with an exact method."""
    iid = _instrument(conn, symbol)
    row = conn.execute(
        "SELECT treatment,factor,method,inputs,note,resolved_by,resolved_at,status "
        "FROM action_resolution WHERE instrument_id=%s AND ex_date=%s AND kind=%s "
        "ORDER BY id DESC LIMIT 1",
        (iid, ex_date, kind),
    ).fetchone()
    if row is None or row[7] in ("verified", "no_adjustment_verified", "rejected"):
        raise ResolveError(f"nothing to verify for {symbol} {kind} {ex_date}")
    treatment, factor, method, inputs, note, resolved_by, resolved_at, _ = row
    if method == "gap":
        raise ResolveError("a gap estimate cannot be verified: re-resolve with an exact method")
    _need_source(source_type, source_url)
    new_status = "verified" if treatment == "factor" else "no_adjustment_verified"
    conn.execute(
        "INSERT INTO action_resolution (instrument_id,ex_date,kind,treatment,factor,method,inputs,"
        "note,resolved_by,resolved_at,status,source_type,source_url,source_hash,confirmed_by,"
        "confirmed_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (iid, ex_date, kind, treatment, factor, method, Jsonb(inputs), note, resolved_by,
         resolved_at, new_status, source_type, source_url, source_hash, by, require_utc(now)),
    )  # fmt: skip


@dataclass(frozen=True)
class Stale:
    symbol: str
    ex_date: date
    kind: str


def stale_resolutions(conn: psycopg.Connection) -> list[Stale]:
    """Latest resolutions whose action is no longer in review (the parser now prices it itself):
    they are ignored by the reader and should be retired by a person."""
    rows = conn.execute(
        "SELECT DISTINCT a.source_symbol, r.ex_date, r.kind FROM action_resolution r "
        "JOIN instrument_alias a ON a.instrument_id=r.instrument_id AND a.source='nse' "
        "AND a.valid_to IS NULL WHERE NOT EXISTS (SELECT 1 FROM corporate_action c "
        "WHERE c.instrument_id=r.instrument_id AND c.ex_date=r.ex_date AND c.kind=r.kind "
        "AND c.status='review') ORDER BY 2, 1, 3"
    )
    return [Stale(*r) for r in rows]
