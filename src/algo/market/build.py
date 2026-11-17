# ruff: noqa: E501
"""Build the market zone table (TODO 6.3): store each day's breadth, then score every day from the stored breadth and the index series.

`refresh_breadth` upserts the breadth counts for days from `since` (the first run uses the start of history; the daily job uses the last few days).
`score` reads ALL stored breadth (the ranking looks back three years), aligns the index series onto those days (a day an index did not print carries
its last close; an index that has no data from the first day on is left out, and the signals that need it come out as None), scores every day with
`zone.score_all` and writes the score, label and regime for days from `since`. Both are idempotent: running again changes nothing but `computed_at`."""

from __future__ import annotations

import json
from datetime import date, datetime

import psycopg
from psycopg.types.json import Jsonb

from algo.market import zone
from algo.market.breadth import daily_breadth

SYMBOLS = {
    "index": "NIFTY 500",
    "vix": "INDIA VIX",
    "bond": "NIFTY GS 10YR",
    "high_beta": "NIFTY HIGHBETA 50",
    "low_vol": "NIFTY LOW VOL 50",
    "small": "NIFTY SMLCAP 100",
    "large": "NIFTY 100",
}


def refresh_breadth(
    conn: psycopg.Connection, since: date, now: datetime, until: date | None = None
) -> int:
    rows = daily_breadth(conn, since, until)
    for b in rows:
        conn.execute(
            "INSERT INTO market_regime_daily (day, universe, advancers, decliners, unchanged, n50, above50, n200, above200, highs, lows, computed_at)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT (day) DO UPDATE SET universe=EXCLUDED.universe, advancers=EXCLUDED.advancers, decliners=EXCLUDED.decliners,"
            " unchanged=EXCLUDED.unchanged, n50=EXCLUDED.n50, above50=EXCLUDED.above50, n200=EXCLUDED.n200, above200=EXCLUDED.above200,"
            " highs=EXCLUDED.highs, lows=EXCLUDED.lows, computed_at=EXCLUDED.computed_at",
            (
                b.day,
                b.universe,
                b.advancers,
                b.decliners,
                b.unchanged,
                b.n50,
                b.above50,
                b.n200,
                b.above200,
                b.highs,
                b.lows,
                now,
            ),
        )
    return len(rows)


def _aligned(conn: psycopg.Connection, days: list[date]) -> dict[str, list[float]]:
    """Each index as one close per day in `days`, carried forward over days it did not print; empty when it starts after the first day."""
    out: dict[str, list[float]] = {}
    for key, symbol in SYMBOLS.items():
        rows = conn.execute(
            "SELECT trade_date, close FROM index_bar_1d WHERE exchange='NSE' AND symbol=%s AND trade_date <= %s ORDER BY trade_date",
            (symbol, days[-1]),
        ).fetchall()
        if not rows or rows[0][0] > days[0]:
            out[key] = []
            continue
        series, k, last = [], 0, float(rows[0][1])
        for d in days:
            while k < len(rows) and rows[k][0] <= d:
                last = float(rows[k][1])
                k += 1
            series.append(last)
        out[key] = series
    return out


def score(conn: psycopg.Connection, since: date, now: datetime) -> int:
    """Score every stored day and write the results for days on or after `since`. Returns the days written. A day with no 50 or 200-day base yet
    (the first months of history) counts breadth as a neutral 50%, so the index history behind the 200-day trend is not thrown away."""
    rows = conn.execute(
        "SELECT day, advancers, decliners, n50, above50, n200, above200, highs, lows FROM market_regime_daily ORDER BY day"
    ).fetchall()
    if not rows:
        return 0
    days = [r[0] for r in rows]
    s = zone.Series(
        **_aligned(conn, days),
        pct_above_50=[100.0 * r[4] / r[3] if r[3] else 50.0 for r in rows],
        pct_above_200=[100.0 * r[6] / r[5] if r[5] else 50.0 for r in rows],
        highs=[r[7] for r in rows],
        lows=[r[8] for r in rows],
        advancers=[r[1] for r in rows],
        decliners=[r[2] for r in rows],
    )
    scored = zone.score_all(s)
    written = 0
    for i, d in enumerate(days):
        if d < since:
            continue
        fg = zone.fear_greed(scored[i])
        reg = zone.regime(s, at=i)
        conn.execute(
            "UPDATE market_regime_daily SET fear_greed=%s, label=%s, trend=%s, volatility=%s, components=%s, computed_at=%s WHERE day=%s",
            (
                None if fg is None else round(fg, 2),
                None if fg is None else zone.zone_label(fg),
                reg.trend,
                reg.volatility,
                Jsonb(
                    json.loads(
                        json.dumps(
                            {k: (None if v is None else round(v, 1)) for k, v in scored[i].items()}
                        )
                    )
                ),
                now,
                d,
            ),
        )
        written += 1
    return written


def refresh(conn: psycopg.Connection, since: date, now: datetime) -> tuple[int, int]:
    """Breadth then scores for days from `since`: (breadth days stored, days scored)."""
    return refresh_breadth(conn, since, now), score(conn, since, now)
