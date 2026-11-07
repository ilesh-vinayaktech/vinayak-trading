"""Load parsed NSE corporate actions and read them back for the adjustment builder."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import psycopg

from algo.core.clock import require_utc
from algo.data.adjust.factors import ActionRecord
from algo.data.lake import LocalLake
from algo.data.providers.nse_corporate_actions import CorporateAction, parse_actions

PROXY = "ex_date_proxy"
IST = ZoneInfo("Asia/Kolkata")


def knowledge_time_for(ex_date: date) -> datetime:
    """Conservative: an action is usable from the start of its ex-date (IST), no earlier."""
    return datetime.combine(ex_date, time(0, 0), IST).astimezone(UTC)


@dataclass
class LoadResult:
    inserted: int = 0
    replaced: int = 0
    unchanged: int = 0
    unknown_symbols: list[str] = field(default_factory=list)


def load_actions(
    conn: psycopg.Connection,
    actions: list[CorporateAction],
    checksum: str,
    now: datetime,
    instrument_id: int | None = None,
) -> LoadResult:
    """instrument_id given => the caller already resolved the issuer (feed symbols are current
    names, which an alias valid at an old ex-date would not match)."""
    now, res, unknown = require_utc(now), LoadResult(), set()
    with conn.transaction():
        for a in actions:
            iid = instrument_id
            if iid is None:
                row = conn.execute(
                    "SELECT instrument_id FROM instrument_alias WHERE source='nse' "
                    "AND source_symbol=%s AND valid_from<=%s AND (valid_to IS NULL OR %s<valid_to)",
                    (a.symbol, a.ex_date, a.ex_date),
                ).fetchone()
                iid = row[0] if row else None
            if iid is None:
                unknown.add(a.symbol)
                continue
            c = a.comp
            cur = conn.execute(
                "INSERT INTO corporate_action (instrument_id,ex_date,record_date,kind,status,num,"
                "den,amount,reason,subject,knowledge_time,knowledge_time_source,source,"
                "raw_checksum,ingested_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'nse',%s,%s) ON CONFLICT DO NOTHING",
                (
                    iid, a.ex_date, a.record_date, c.kind, c.status, c.num, c.den, c.amount,
                    c.reason, a.subject, knowledge_time_for(a.ex_date), PROXY, checksum, now,
                ),
            )  # fmt: skip
            if cur.rowcount:
                res.inserted += 1
            else:
                res.unchanged += 1
    res.unknown_symbols = sorted(unknown)
    return res


def records_for(
    conn: psycopg.Connection, instrument_id: int, *, strict: bool = False
) -> list[ActionRecord]:
    """Actions for the adjustment builder. A review-status action takes its latest human
    resolution into account (resolutions are keyed by (instrument, ex_date, kind), so rebuilding
    corporate_action from raw JSON never loses them):
      verified                              -> price-only factor, always applied
      provisional (estimate)                -> strict: stays a blocking review item;
                                               research: applied but flagged provisional
      no_adjustment_verified / ignored_with_reason / rejected -> a documented decision that no
                                               adjustment is needed: not an action
    ponytail: a resolved factor is known from the ex-date; a demerger's child price is only known
    after listing, so point-in-time reads are slightly optimistic until known_from exists."""
    rows = conn.execute(
        "SELECT c.ex_date,c.kind,c.status,c.num,c.den,c.amount,c.knowledge_time,"
        "r.status,r.treatment,r.factor FROM corporate_action c "
        "LEFT JOIN LATERAL (SELECT status,treatment,factor FROM action_resolution r "
        "  WHERE r.instrument_id=c.instrument_id AND r.ex_date=c.ex_date AND r.kind=c.kind "
        "  ORDER BY r.id DESC LIMIT 1) r ON c.status='review' "
        "WHERE c.instrument_id=%s ORDER BY c.ex_date,c.id",
        (instrument_id,),
    )
    out: list[ActionRecord] = []
    for ex, kind, status, num, den, amount, kt, res_status, treatment, factor in rows:
        if treatment is None or (strict and res_status == "provisional"):
            out.append(ActionRecord(ex, kind, status, num, den, amount, kt))
        elif treatment == "factor":
            provisional = res_status == "provisional"
            out.append(ActionRecord(ex, "resolved", "ok", Decimal(1), factor, None, kt, provisional))
        # treatment == "ignore": a documented decision that no price adjustment is needed
    return out


API = "https://www.nseindia.com/api/corporates-corporateActions"


def ingest_symbol(
    conn: psycopg.Connection,
    lake: LocalLake,
    get_json: Callable[[str], bytes],
    symbol: str,
    now: datetime,
    since: date = date(2005, 1, 1),
) -> LoadResult | None:
    """Fetch one issuer's full action history, keep the raw JSON, parse, load. None = unknown."""
    row = conn.execute(
        "SELECT instrument_id FROM instrument_alias WHERE source='nse' AND source_symbol=%s "
        "AND valid_to IS NULL",
        (symbol,),
    ).fetchone()
    if row is None:
        return None
    today = require_utc(now).date()
    url = (
        f"{API}?index=equities&symbol={symbol}&from_date={since:%d-%m-%Y}&to_date={today:%d-%m-%Y}"
    )
    raw = get_json(url)
    m = lake.put("nse", f"corporate_actions_{symbol}", today, raw, url=url, fetched_at=now)
    return _replace(conn, row[0], raw, m.checksum, now)


def _replace(
    conn: psycopg.Connection, instrument_id: int, raw: bytes, checksum: str, now: datetime
) -> LoadResult:
    """corporate_action is a derived table: an issuer's rows are rebuilt from its raw JSON in one
    transaction (the lake keeps every raw version). ponytail: manual review resolutions will need
    their own table so a rebuild cannot erase them."""
    actions, _ = parse_actions(raw)
    with conn.transaction():
        cur = conn.execute(
            "DELETE FROM corporate_action WHERE instrument_id=%s AND source='nse'", (instrument_id,)
        )
        res = load_actions(conn, actions, checksum, now, instrument_id=instrument_id)
        res.replaced = cur.rowcount
    return res


def reparse_symbol(
    conn: psycopg.Connection, lake: LocalLake, symbol: str, now: datetime
) -> LoadResult | None:
    """Rebuild from the newest raw JSON already in the lake (no network): use after parser fixes."""
    row = conn.execute(
        "SELECT instrument_id FROM instrument_alias WHERE source='nse' AND source_symbol=%s "
        "AND valid_to IS NULL",
        (symbol,),
    ).fetchone()
    m = lake.latest("nse", f"corporate_actions_{symbol}")
    if row is None or m is None:
        return None
    return _replace(conn, row[0], lake.get(m), m.checksum, now)
