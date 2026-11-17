# ruff: noqa: E501
"""Market breadth (TODO 6.3): for each trading day, how many liquid stocks rose, fell, sit above their 50 and 200-day averages, or closed at a new 52-week
high or low (strictly above every one of the previous 251 closes, or below them all: a flat stock is neither). Counted in the database from `bar_canonical` (one row per stock and day, the preferred source winning) with window functions, so a full
history is one query. A stock counts only on days it traded and only when its 20-day average traded value is at least 1 crore; the above-average and new-high
counts also need the full 50, 200 or 252 days of that stock's own history, so a new listing is not counted as weak. Closes are used throughout."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import psycopg

MIN_TRADED_VALUE = (
    10_000_000  # 1 crore rupees: a 20-day average of close x volume below this is too thin to count
)
LOOKBACK_DAYS = (
    420  # calendar days of earlier bars needed so the first day asked for already has its averages
)

SQL = """
WITH b AS (
  SELECT instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date AS d, close,
         lag(close) OVER w AS prev,
         avg(close) OVER w50 AS sma50, count(*) OVER w50 AS n50,
         avg(close) OVER w200 AS sma200, count(*) OVER w200 AS n200,
         max(close) OVER wp AS hi, min(close) OVER wp AS lo, count(*) OVER w252 AS n252,
         avg(close * volume) OVER w20 AS tv20
  FROM bar_canonical
  WHERE ts >= (%(since)s::date - %(lookback)s) AND close > 0
  WINDOW w AS (PARTITION BY instrument_id ORDER BY ts),
         w20 AS (w ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
         w50 AS (w ROWS BETWEEN 49 PRECEDING AND CURRENT ROW),
         w200 AS (w ROWS BETWEEN 199 PRECEDING AND CURRENT ROW),
         w252 AS (w ROWS BETWEEN 251 PRECEDING AND CURRENT ROW),
         wp AS (w ROWS BETWEEN 251 PRECEDING AND 1 PRECEDING)
)
SELECT d, count(*),
       count(*) FILTER (WHERE close > prev), count(*) FILTER (WHERE close < prev), count(*) FILTER (WHERE close = prev),
       count(*) FILTER (WHERE n50 = 50), count(*) FILTER (WHERE n50 = 50 AND close > sma50),
       count(*) FILTER (WHERE n200 = 200), count(*) FILTER (WHERE n200 = 200 AND close > sma200),
       count(*) FILTER (WHERE n252 = 252 AND close > hi), count(*) FILTER (WHERE n252 = 252 AND close < lo)
FROM b
WHERE d >= %(since)s AND (%(until)s::date IS NULL OR d <= %(until)s) AND tv20 >= %(min_tv)s
GROUP BY d ORDER BY d
"""


@dataclass(frozen=True)
class Breadth:
    day: date
    universe: int
    advancers: int
    decliners: int
    unchanged: int
    n50: int
    above50: int
    n200: int
    above200: int
    highs: int
    lows: int

    @property
    def pct_above_50(self) -> float | None:
        return 100.0 * self.above50 / self.n50 if self.n50 else None

    @property
    def pct_above_200(self) -> float | None:
        return 100.0 * self.above200 / self.n200 if self.n200 else None


def daily_breadth(
    conn: psycopg.Connection, since: date, until: date | None = None
) -> list[Breadth]:
    rows = conn.execute(
        SQL, {"since": since, "until": until, "lookback": LOOKBACK_DAYS, "min_tv": MIN_TRADED_VALUE}
    ).fetchall()
    return [Breadth(*r) for r in rows]
