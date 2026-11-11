# ruff: noqa: E501
"""Read path for Kite 1-minute bars. Kite serves prices and volumes already adjusted for the splits and bonuses with an
ex-date up to the day it was fetched (`adjusted_through`, kept on every row). A reader must therefore apply only the
splits AFTER that day, plus the price-only actions (demerger, rights) that Kite never applies:
  adjust='none'   exactly as stored (adjusted through each row's own basis day; the raw traded prices are not recoverable)
  adjust='split'  continuous across every split, bonus and price-only action; volume scaled inversely
Dividends are not offered here (Kite does not adjust for them and the 1-minute series is not used for total return).
Unpriced actions are reported in `History.unapplied`; strict=True refuses instead of returning prices they make wrong.
ponytail: hindsight only (no as_of / knowledge-time slicing yet); add when a backtest needs point-in-time minutes."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import psycopg

from algo.data.adjust.factors import PRICE_KINDS, SPLIT_KINDS, build_adjustments, factor_on
from algo.data.corporate_actions import records_for
from algo.data.reader import AdjBar, History, UnadjustableError, _version

IST = ZoneInfo("Asia/Kolkata")
MODES = ("none", "split")


def minute_history(
    conn: psycopg.Connection,
    instrument_id: int,
    start: date,
    end: date,
    *,
    adjust: str = "none",
    strict: bool = False,
    source: str = "kite",
) -> History:
    if adjust not in MODES:
        raise ValueError(f"adjust must be one of {MODES}")
    rows = conn.execute(
        "SELECT DISTINCT ON (ts) ts,open,high,low,close,volume,adjusted_through FROM bar_1m "
        "WHERE instrument_id=%s AND source=%s AND ts>=%s AND ts<%s ORDER BY ts, dataset_version DESC",
        (
            instrument_id,
            source,
            datetime.combine(start, time(0), IST),
            datetime.combine(end + timedelta(days=1), time(0), IST),
        ),
    ).fetchall()
    if not rows:
        return History([])
    if adjust == "none":
        return History(
            [AdjBar(r[0], r[1], r[2], r[3], r[4], r[5], Decimal(1), instrument_id) for r in rows],
            adjustment_version=_version("none", []),
        )
    recs = records_for(conn, instrument_id, strict=strict)
    built = build_adjustments(
        [r for r in recs if r.kind in (*SPLIT_KINDS, *PRICE_KINDS) or r.status == "review"],
        lambda _: Decimal(1),  # only dividends need a previous close, and none are selected here
    )
    first_day = rows[0][0].astimezone(IST).date()
    unapplied = [u for u in built.unapplied if u.ex_date > first_day and u.kind != "dividend"]
    provisional = [r for r in recs if r.provisional and r.ex_date > first_day]
    if strict and unapplied:
        raise UnadjustableError(
            "unpriced corporate actions affect these prices: "
            + ", ".join(f"{u.kind}@{u.ex_date}" for u in unapplied)
        )
    bars = []
    for ts, o, h, low, c, v, through in rows:
        d = ts.astimezone(IST).date()
        f = factor_on(built.adjustments, d, applied_through=through)
        fs = factor_on(built.adjustments, d, volume=True, applied_through=through)
        bars.append(AdjBar(ts, o * f, h * f, low * f, c * f, v / fs, f, instrument_id))
    return History(bars, unapplied, provisional, _version("split", recs))
