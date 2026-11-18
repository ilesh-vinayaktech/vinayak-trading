# ruff: noqa: E501
"""The expected-range forecast, live (spec docs/forecast/volatility_v1_spec.md, version `range-ridge-v1`): made before the open from the sessions up to the last completed one, India VIX and the US
overnight, written once to `range_forecast_log` and never replaced, then resolved with the session's actual range. The model is `algo.market.volatility`; this module only gathers the data,
applies the guards (a forecast is made only on a trading day, and only when the last completed session is the day before) and stores the result. A research forecast: independent of the direction
forecasts (a failure of one never stops the other)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import psycopg
from psycopg.types.json import Jsonb

from algo.data import global_markets as g
from algo.live.market_calendar import IST, windows_for
from algo.market import volatility as v

VERSION = "range-ridge-v1"


@dataclass(frozen=True)
class Outcome:
    status: str  # made | exists | closed | stale | no_inputs | too_little_history
    detail: str
    forecast_range: float | None = None


def _trading_day(conn: psycopg.Connection, d: date) -> bool:
    return bool(windows_for(conn, d))


def last_completed(conn: psycopg.Connection, today: date) -> date:
    """The last trading day before `today` (the session whose close the forecast is made after)."""
    d = today - timedelta(days=1)
    for _ in range(14):
        if _trading_day(conn, d):
            return d
        d -= timedelta(days=1)
    return d


def _sessions(conn: psycopg.Connection, through: date) -> list[v.Session]:
    return [v.Session(d, float(o), float(h), float(lo), float(c)) for d, o, h, lo, c in conn.execute(
        "SELECT trade_date, open, high, low, close FROM index_bar_1d WHERE exchange='NSE' AND symbol='NIFTY 500' AND trade_date <= %s ORDER BY trade_date", (through,)
    ).fetchall()]  # fmt: skip


def make(conn: psycopg.Connection, now: datetime) -> Outcome:
    """Make today's forecast if it is due. Safe to repeat: an existing forecast is left exactly as it was."""
    today = now.astimezone(IST).date()
    if not _trading_day(conn, today):
        return Outcome("closed", f"{today} is not a trading day: nothing to forecast")
    prev = last_completed(conn, today)
    sessions = _sessions(conn, prev)
    if not sessions or sessions[-1].day != prev:
        return Outcome(
            "stale",
            f"the last Nifty 500 candle is {sessions[-1].day if sessions else 'missing'}, not {prev}: load the index candles first; no forecast made",
        )
    if conn.execute(
        "SELECT 1 FROM range_forecast_log WHERE as_of=%s AND model_version=%s", (prev, VERSION)
    ).fetchone():
        return Outcome(
            "exists", f"the forecast after {prev} was already made and is left as it was"
        )
    vix = {
        d: float(c)
        for d, c in conn.execute(
            "SELECT trade_date, close FROM index_bar_1d WHERE exchange='NSE' AND symbol='INDIA VIX' AND trade_date <= %s",
            (prev,),
        )
    }
    sp, vx = g.series(conn, "SP500"), g.series(conn, "VIXUS")
    night = {}
    for s in sessions:
        a, b = g.last_session_return(sp, s.day), g.last_session_return(vx, s.day)
        if a is not None and b is not None:
            night[s.day] = (a, b)
    expected_us = (
        today - timedelta(days=1)
    )  # the US session that has just closed: the latest weekday before today's date (a US holiday means no forecast that day)
    while expected_us.weekday() >= 5:
        expected_us -= timedelta(days=1)
    if (
        max((r[0] for r in sp if r[0] < today), default=None) != expected_us
        or max((r[0] for r in vx if r[0] < today), default=None) != expected_us
    ):
        return Outcome(
            "no_inputs",
            f"the S&P 500 and US VIX closes for the US session of {expected_us} are not both in (not loaded yet, or a US holiday): no forecast made",
        )
    ahead = (
        g.last_session_return(sp, today),
        g.last_session_return(vx, today),
    )  # the US sessions before today's open
    x_next = v.next_row(
        sessions, vix, None if ahead[0] is None or ahead[1] is None else (ahead[0], ahead[1])
    )
    if x_next is None:
        return Outcome(
            "no_inputs",
            f"the US closes before {today} or India VIX for {prev} are not in yet: no forecast made",
        )
    days, x, yr, _ = v.build(sessions, vix, night)
    got = v.forecast_next(x, yr, x_next)
    if got is None:
        return Outcome("too_little_history", f"{len(yr)} rows, {v.MIN_TRAIN} needed")
    forecast, n_train = got
    feats = dict(zip(v.FEATURES, (round(float(q), 6) for q in x_next), strict=True))
    conn.execute(
        "INSERT INTO range_forecast_log (as_of, model_version, made_at, forecast_range, features, train_through, n_train) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
        (prev, VERSION, now, forecast, Jsonb(feats), days[n_train - 1], n_train),
    )  # a forecast is written once
    return Outcome(
        "made",
        f"expected range for {today}: {forecast:.3f}% of the open (after {prev}; {n_train} sessions learned from, through {days[n_train - 1]})",
        forecast,
    )


def resolve(conn: psycopg.Connection) -> int:
    """Fill in the actual range of every forecast whose session has traded; the forecast itself is never touched. Returns how many were resolved."""
    n = 0
    for as_of, ver in conn.execute(
        "SELECT as_of, model_version FROM range_forecast_log WHERE actual_range IS NULL"
    ).fetchall():
        nxt = conn.execute(
            "SELECT trade_date, open, high, low FROM index_bar_1d WHERE exchange='NSE' AND symbol='NIFTY 500' AND trade_date > %s ORDER BY trade_date LIMIT 1",
            (as_of,),
        ).fetchone()
        if nxt is None:
            continue
        actual = v.range_pct(v.Session(nxt[0], float(nxt[1]), float(nxt[2]), float(nxt[3]), 0.0))
        conn.execute(
            "UPDATE range_forecast_log SET actual_range=%s, target_day=%s, resolved_on=%s WHERE as_of=%s AND model_version=%s AND actual_range IS NULL",
            (actual, nxt[0], nxt[0], as_of, ver),
        )
        n += 1
    return n
