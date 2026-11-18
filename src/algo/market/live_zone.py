# ruff: noqa: E501
"""The market zone as it stands right now (TODO 6.3 follow-up): the nightly zone is a snapshot of the last close; this works out today's reading from live prices.

Breadth: `refresh_baseline` stores, per stock, what its history before today contributes (previous close, the sums behind the 50 and 200-day averages, the 252-day high and
low, the traded value); `live_breadth` adds each stock's live price to that and counts exactly as `breadth.SQL` does for a finished day (a test pins the two to the same
numbers). Indices: the zone's own index series (Nifty 500, India VIX, bonds, high beta, low volatility, small and large caps) get today's live level in place of a close.
The day is then scored with the very same `zone` functions against the same history, so a live reading is a normal reading with a moving last day. When any piece is
missing (no baseline for the last trading day, no live prices, too few stocks quoted) there is no live reading and the caller keeps the snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

import psycopg

from algo.live.index_store import read_quotes
from algo.live.market_calendar import IST
from algo.market import build, zone
from algo.market.breadth import LOOKBACK_DAYS, MIN_TRADED_VALUE, Breadth

MIN_COVERAGE = 0.5  # fewer stocks than this share of the baseline quoted today: the feed is not really on, so no live reading

BASELINE_SQL = """
WITH b AS (
  SELECT instrument_id, close, volume, row_number() OVER (PARTITION BY instrument_id ORDER BY ts DESC) rn
  FROM bar_canonical WHERE ts >= (%(today)s::date - %(lookback)s) AND ts < %(today)s::date AND close > 0
)
SELECT instrument_id, max(close) FILTER (WHERE rn = 1),
       count(*) FILTER (WHERE rn <= 49), sum(close) FILTER (WHERE rn <= 49),
       count(*) FILTER (WHERE rn <= 199), sum(close) FILTER (WHERE rn <= 199),
       count(*) FILTER (WHERE rn <= 251), max(close) FILTER (WHERE rn <= 251), min(close) FILTER (WHERE rn <= 251),
       count(*) FILTER (WHERE rn <= 19), coalesce(sum(close * volume) FILTER (WHERE rn <= 19), 0)
FROM b GROUP BY instrument_id
"""


def last_bar(conn: psycopg.Connection, today: date) -> date | None:
    """The last trading day with daily bars before `today`. Read from the bars table with a time bound (the `bar_canonical` view takes seconds for the same answer)."""
    row = conn.execute(
        "SELECT max((ts AT TIME ZONE 'Asia/Kolkata')::date) FROM bar_1d WHERE ts >= %s::date - 15 AND ts < %s::date", (today, today)
    ).fetchone()  # fmt: skip
    return row[0] if row else None


def refresh_baseline(conn: psycopg.Connection, today: date, now: datetime) -> int:
    """Store the baseline for the session `today` from every bar before it; older generations are dropped. Returns the stocks stored (0 when there are no earlier bars)."""
    last = last_bar(conn, today)
    if last is None:
        return 0
    rows = conn.execute(BASELINE_SQL, {"today": today, "lookback": LOOKBACK_DAYS}).fetchall()
    conn.execute("DELETE FROM breadth_baseline")
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO breadth_baseline (last_bar, instrument_id, prev_close, c49, s49, c199, s199, c251, hi251, lo251, c19, tv19, computed_at)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [(last, *r, now) for r in rows],
        )
    return len(rows)


def live_breadth(conn: psycopg.Connection, today: date) -> Breadth | None:
    """Today's breadth from live prices, or None when the baseline is not for the last trading day or too few stocks are quoted."""
    last = last_bar(conn, today)
    if last is None:
        return None
    start = datetime.combine(today, time(0), IST)
    row = conn.execute(
        """
        WITH l AS (
          SELECT bb.*, q.ltp AS close, coalesce(q.volume, 0) AS vol
          FROM breadth_baseline bb JOIN live_quote q USING (instrument_id)
          WHERE bb.last_bar = %(last)s AND q.updated_at >= %(start)s AND q.ltp > 0
        ), t AS (SELECT count(*) FROM breadth_baseline WHERE last_bar = %(last)s)
        SELECT (SELECT * FROM t), count(*) FILTER (WHERE (tv19 + close * vol) / (c19 + 1) >= %(min_tv)s),
               count(*) FILTER (WHERE (tv19 + close * vol) / (c19 + 1) >= %(min_tv)s AND close > prev_close),
               count(*) FILTER (WHERE (tv19 + close * vol) / (c19 + 1) >= %(min_tv)s AND close < prev_close),
               count(*) FILTER (WHERE (tv19 + close * vol) / (c19 + 1) >= %(min_tv)s AND close = prev_close),
               count(*) FILTER (WHERE (tv19 + close * vol) / (c19 + 1) >= %(min_tv)s AND c49 = 49),
               count(*) FILTER (WHERE (tv19 + close * vol) / (c19 + 1) >= %(min_tv)s AND c49 = 49 AND close > (s49 + close) / 50),
               count(*) FILTER (WHERE (tv19 + close * vol) / (c19 + 1) >= %(min_tv)s AND c199 = 199),
               count(*) FILTER (WHERE (tv19 + close * vol) / (c19 + 1) >= %(min_tv)s AND c199 = 199 AND close > (s199 + close) / 200),
               count(*) FILTER (WHERE (tv19 + close * vol) / (c19 + 1) >= %(min_tv)s AND c251 = 251 AND close > hi251),
               count(*) FILTER (WHERE (tv19 + close * vol) / (c19 + 1) >= %(min_tv)s AND c251 = 251 AND close < lo251),
               count(*)
        FROM l
        """,
        {"last": last, "start": start, "min_tv": MIN_TRADED_VALUE},
    ).fetchone()
    assert row is not None  # an aggregate always returns a row
    total, universe, adv, dec, unch, n50, a50, n200, a200, hi, lo, quoted = row
    if not total or quoted < MIN_COVERAGE * total or universe == 0:
        return None
    return Breadth(today, universe, adv, dec, unch, n50, a50, n200, a200, hi, lo)


@dataclass(frozen=True)
class LiveZone:
    day: date
    breadth: Breadth
    fear_greed: float | None
    label: str | None
    trend: str
    volatility: str
    components: dict[str, float | None]
    history: list[tuple[date, float | None, str]]  # the stored days with today's live reading last


def live_zone(conn: psycopg.Connection, today: date, history_days: int = 260) -> LiveZone | None:
    """Today's zone from live prices scored against the stored history; None when any piece is missing (the snapshot stays)."""
    b = live_breadth(conn, today)
    if b is None:
        return None
    rows = conn.execute(
        "SELECT day, advancers, decliners, n50, above50, n200, above200, highs, lows FROM market_regime_daily WHERE day < %s ORDER BY day", (today,)
    ).fetchall()  # fmt: skip
    if not rows:
        return None
    days = [r[0] for r in rows] + [today]
    aligned = build._aligned(conn, days)
    live = read_quotes(conn, list(build.SYMBOLS.values()), datetime.combine(today, time(0), IST))
    for key, symbol in build.SYMBOLS.items():
        if aligned[key] and symbol in live:
            aligned[key][-1] = live[symbol][
                0
            ]  # today's level in place of the carried-forward last close
    s = zone.Series(
        **aligned,
        pct_above_50=[100.0 * r[4] / r[3] if r[3] else 50.0 for r in rows]
        + [b.pct_above_50 if b.pct_above_50 is not None else 50.0],
        pct_above_200=[100.0 * r[6] / r[5] if r[5] else 50.0 for r in rows]
        + [b.pct_above_200 if b.pct_above_200 is not None else 50.0],
        highs=[r[7] for r in rows] + [b.highs],
        lows=[r[8] for r in rows] + [b.lows],
        advancers=[r[1] for r in rows] + [b.advancers],
        decliners=[r[2] for r in rows] + [b.decliners],
    )
    comps = zone.components(s, at=len(days) - 1)
    fg = zone.fear_greed(comps)
    reg = zone.regime(s, at=len(days) - 1)
    stored: list[Any] = conn.execute(
        "SELECT day, fear_greed, trend FROM market_regime_daily WHERE fear_greed IS NOT NULL AND day < %s ORDER BY day DESC LIMIT %s", (today, history_days)
    ).fetchall()  # fmt: skip
    hist = [(d, None if f is None else float(f), t) for d, f, t in reversed(stored)] + [
        (today, fg, reg.trend)
    ]
    return LiveZone(
        today,
        b,
        fg,
        None if fg is None else zone.zone_label(fg),
        reg.trend,
        reg.volatility,
        comps,
        hist,
    )
