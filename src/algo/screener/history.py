# ruff: noqa: E501
"""The swing score as it stood on each past day (TODO 6.2a), so the score can be tested against what happened next.

Every input is rebuilt as it was KNOWN on the day, never from today's table:
  prices           bars up to the day only; a window never reaches back across a split or bonus (it starts at the latest ex-date on or before the day), as the live table does
  delivery         the day's own delivery % against the average of the 20 rows before it
  holdings         only filings broadcast on or before the day (the newest, and its change against the filing for the previous period)
  deals, insiders  only those dated on or before the day, in the same 30 / 90-day windows as the live fields
  fundamentals     only filings filed on or before the day (algo.data.ratios.known_quarters), the basis picked from what was filed by then
The scores come from the same `score_universe` as today's, ranked against the stocks of THAT day. Delisted stocks are included (no survivorship).
Prices here are float64 (the score is a rank, not money). Cutting the data off at a day must not change that day's scores: tested."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import psycopg

from algo.data import ratios as fr
from algo.indicators.catalog import Bars, compute
from algo.screener.score import COMPONENTS, SIGNALS, score_universe
from algo.screener.smart_money import CRORE, DEAL_DAYS, DELIVERY_DAYS, INSIDER_DAYS
from algo.screener.snapshot import quarters_since

IST = ZoneInfo("Asia/Kolkata")
LOOKBACK_DAYS = (
    460  # calendar days of earlier bars so the first day asked for already has 252 sessions
)
FILING_YEARS = 3
UNFILED_HOLDING_DAYS = 45  # a holding filing with no broadcast time counts as known this long after its period end (never earlier)
FIELDS = tuple(f for signals in SIGNALS.values() for f, _, _ in signals)
RATIO_KEYS = ("roe", "roce", "profit_growth", "debt_to_equity")
HOLD_COLS = ("promoter_pct", "fii_pct", "dii_pct", "mf_pct")
HOLD_KEYS = (*HOLD_COLS, *(c.replace("_pct", "_change") for c in HOLD_COLS))


def week_ends(conn: psycopg.Connection, since: date, until: date) -> list[date]:
    """The last trading day of each week between the two dates (the days the backfill stores)."""
    return [
        r[0]
        for r in conn.execute(
            "SELECT max(d) FROM (SELECT DISTINCT (ts AT TIME ZONE 'Asia/Kolkata')::date AS d FROM bar_1d WHERE source='nse' AND ts >= %s AND ts < %s::date + 1) x"
            " GROUP BY date_trunc('week', d) ORDER BY 1",
            (since, until),
        )
    ]


# --- prices ----------------------------------------------------------------------------------------------------------------


def _indicator(rows: pd.DataFrame, spec: str, key: str, min_bars: int) -> pd.Series:
    """One output of the live indicator catalog over one stock's run of bars since its last split (NaN where the catalog has no value)."""
    if len(rows) <= min_bars:
        return pd.Series(np.nan, index=rows.index)
    cols = [[Decimal(str(x)) for x in rows[c]] for c in ("open", "high", "low", "close", "volume")]
    series = compute(spec, Bars(*cols))[2][key]
    return pd.Series([np.nan if v is None else float(v) for v in series], index=rows.index)


def _adx(rows: pd.DataFrame) -> pd.Series:
    return _indicator(rows, "adx:14", "adx", 28)


EXTRA = (
    "chg_1d",
    "price_vs_sma200",
    "sma50_vs_sma200",
    "pct_from_52w_low",
    "rsi_14",
    "macd_hist",
)  # what the technical presets read beyond the score's inputs


def technical_frame(
    bars: pd.DataFrame, splits: pd.DataFrame, days: Sequence[date], extra: bool = False
) -> pd.DataFrame:
    """The price and volume fields on each of `days`, for every stock that has a bar that day; with `extra`, also the EXTRA fields (slower: RSI and MACD).
    bars: instrument_id, d, open, high, low, close, volume, delivery_qty. splits: instrument_id, ex_date."""
    b = bars.sort_values(["instrument_id", "d"]).reset_index(drop=True)
    seg = np.zeros(
        len(b), dtype=np.int64
    )  # splits on or before each bar's day: a window starts after the latest one
    for iid, ex in splits.groupby("instrument_id")["ex_date"]:
        idx = b.index[b["instrument_id"] == iid]
        if len(idx):
            seg[idx] = np.searchsorted(
                np.sort(ex.to_numpy()), b.loc[idx, "d"].to_numpy(), side="right"
            )
    b["seg"] = seg
    g = b.groupby(["instrument_id", "seg"], sort=False)
    b["chg_1m"] = (b["close"] / g["close"].shift(21) - 1) * 100
    b["chg_3m"] = (b["close"] / g["close"].shift(63) - 1) * 100
    b["price_vs_sma50"] = (
        b["close"] / g["close"].transform(lambda s: s.rolling(50).mean()) - 1
    ) * 100
    b["pct_from_52w_high"] = (
        b["close"] / g["close"].transform(lambda s: s.rolling(252, min_periods=126).max()) - 1
    ) * 100
    prior = g["volume"].transform(lambda s: s.shift(1).rolling(20).mean())
    b["volume_ratio"] = (b["volume"] / prior).where(prior > 0)
    b["adx_14"] = g["close"].transform(lambda s: _adx(b.loc[s.index]))
    if extra:
        sma50 = g["close"].transform(lambda s: s.rolling(50).mean())
        sma200 = g["close"].transform(lambda s: s.rolling(200).mean())
        b["chg_1d"] = (b["close"] / g["close"].shift(1) - 1) * 100
        b["price_vs_sma200"] = (b["close"] / sma200 - 1) * 100
        b["sma50_vs_sma200"] = (sma50 / sma200 - 1) * 100
        b["pct_from_52w_low"] = (
            b["close"] / g["close"].transform(lambda s: s.rolling(252, min_periods=126).min()) - 1
        ) * 100
        b["rsi_14"] = g["close"].transform(
            lambda s: _indicator(b.loc[s.index], "rsi:14", "value", 14)
        )
        b["macd_hist"] = g["close"].transform(
            lambda s: _indicator(b.loc[s.index], "macd", "hist", 35)
        )
    by_stock = b[
        "instrument_id"
    ]  # liquidity and delivery are not cut at a split: a share count does not change what traded
    b["turnover_cr"] = (b["close"] * b["volume"]).groupby(by_stock).transform(
        lambda s: s.rolling(20).mean()
    ) / 1e7
    pct = (100 * b["delivery_qty"] / b["volume"]).where(b["volume"] > 0)
    avg = pct.groupby(by_stock).transform(
        lambda s: s.shift(1).rolling(DELIVERY_DAYS, min_periods=1).mean()
    )
    b["delivery_pct"] = pct
    b["delivery_vs_avg"] = (pct / avg).where(avg > 0)
    keep = b[b["d"].isin(set(days))]
    cols = [
        "instrument_id",
        "d",
        "turnover_cr",
        *[f for f in FIELDS if f in keep.columns],
        *([e for e in EXTRA if e in keep.columns] if extra else []),
    ]
    return keep[cols].reset_index(drop=True)


def load_bars(conn: psycopg.Connection, first: date, last: date) -> pd.DataFrame:
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, open::float8, high::float8, low::float8, close::float8, volume::float8,"
        " CASE WHEN series = 'EQ' THEN delivery_qty::float8 END FROM bar_1d WHERE source='nse' AND ts >= %s::date - %s AND ts < %s::date + 1"
        " ORDER BY instrument_id, ts, dataset_version DESC",
        (first, LOOKBACK_DAYS, last),
    ).fetchall()
    return pd.DataFrame(
        rows,
        columns=["instrument_id", "d", "open", "high", "low", "close", "volume", "delivery_qty"],
    )


# --- smart money, as known on each day -------------------------------------------------------------------------------------


def _windowed(
    conn: psycopg.Connection, days: Sequence[date], sql: str, window: int
) -> dict[tuple[date, str], float]:
    """{(day, symbol): net crore} over the `window` days up to each day. `sql` takes (after, up to) and returns (event date, symbol, signed value)."""
    events = pd.DataFrame(
        conn.execute(sql, (min(days) - timedelta(days=window), max(days))).fetchall(),
        columns=["d", "symbol", "v"],
    )
    out: dict[tuple[date, str], float] = {}
    if events.empty:
        return out
    events["d"] = pd.to_datetime(events["d"])
    for day in days:
        cut = events[
            (events["d"] > pd.Timestamp(day - timedelta(days=window)))
            & (events["d"] <= pd.Timestamp(day))
        ]
        for sym, v in cut.groupby("symbol")["v"].sum().items():
            out[(day, str(sym))] = float(v) / float(CRORE)
    return out


def _holdings_known(
    conn: psycopg.Connection, days: Sequence[date]
) -> dict[tuple[date, str], dict[str, float]]:
    rows = conn.execute(
        "SELECT symbol, period_end, min(coalesce((broadcast_at AT TIME ZONE 'Asia/Kolkata')::date, period_end + %s)), "
        + ", ".join(
            f"(array_agg({c} ORDER BY broadcast_at DESC NULLS LAST))[1]::float8" for c in HOLD_COLS
        )
        + " FROM nse_shareholding GROUP BY symbol, period_end ORDER BY symbol, period_end",
        (UNFILED_HOLDING_DAYS,),
    ).fetchall()
    f = pd.DataFrame(rows, columns=["symbol", "period_end", "known", *HOLD_COLS])
    out: dict[tuple[date, str], dict[str, float]] = {}
    if f.empty:
        return out
    for c in (
        HOLD_COLS
    ):  # change against the filing for the previous period, only where both report the figure
        f[c.replace("_pct", "_change")] = f.groupby("symbol")[c].diff()
    f["known"] = pd.to_datetime(f["known"])
    for day in days:
        seen = f[f["known"] <= pd.Timestamp(day)]
        for rec in (
            seen.groupby("symbol").tail(1).to_dict("records")
        ):  # rows are in period order, so the last is the newest period known
            vals = {k: float(rec[k]) for k in HOLD_KEYS if pd.notna(rec[k])}
            if vals:
                out[(day, str(rec["symbol"]))] = vals
    return out


def smart_fields(
    conn: psycopg.Connection, days: Sequence[date]
) -> dict[tuple[date, str], dict[str, float]]:
    """{(day, symbol): fields} for the NSE-sourced figures, each as known on that day."""
    out: dict[tuple[date, str], dict[str, float]] = defaultdict(dict)
    deals = "SELECT trade_date, symbol, (CASE side WHEN 'BUY' THEN quantity * price ELSE -quantity * price END)::float8 FROM nse_bulk_block_deal WHERE trade_date > %s AND trade_date <= %s"
    day_of = "(broadcast_at AT TIME ZONE 'Asia/Kolkata')::date"
    insiders = (
        f"SELECT {day_of}, symbol, (CASE lower(transaction_type) WHEN 'buy' THEN value WHEN 'sell' THEN -value ELSE 0 END)::float8"
        f" FROM nse_insider_trade WHERE {day_of} > %s AND {day_of} <= %s AND value IS NOT NULL"
    )
    for key, sql, window in (
        ("deal_net_30d", deals, DEAL_DAYS),
        ("insider_net_90d", insiders, INSIDER_DAYS),
    ):
        for (day, sym), v in _windowed(conn, days, sql, window).items():
            out[(day, sym)][key] = v
    for key2, held in _holdings_known(conn, days).items():
        out[key2].update(held)
    return out


# --- fundamentals, as filed by each day ------------------------------------------------------------------------------------


def fundamental_fields(
    conn: psycopg.Connection, days: Sequence[date], ids: Sequence[int]
) -> dict[tuple[date, int], dict[str, float]]:
    """{(day, instrument_id): roe, roce, profit_growth, debt_to_equity} from the filings known on that day."""
    out: dict[tuple[date, int], dict[str, float]] = {}
    ds = sorted(days)
    by_stock: dict[int, dict[str, list[fr.Quarter]]] = defaultdict(dict)
    for (iid, basis), qs in quarters_since(
        conn, ds[0] - timedelta(days=365 * FILING_YEARS), list(ids)
    ).items():
        by_stock[iid][basis] = qs
    for iid, bases in by_stock.items():
        state: list[tuple[datetime, dict[str, float]]] = []
        for t in sorted({q.filed_at for qs in bases.values() for q in qs}):
            known = next(
                (
                    k
                    for b in ("CONSOLIDATED", "STANDALONE")
                    if b in bases and (k := fr.known_quarters(bases[b], t))
                ),
                [],
            )
            if known:
                got = fr.compute(known, None)
                state.append(
                    (
                        t,
                        {
                            k: float(v)
                            for k in RATIO_KEYS
                            if k in got and (v := got[k].value) is not None
                        },
                    )
                )
        j = -1
        for day in ds:
            while j + 1 < len(state) and state[j + 1][0].astimezone(IST).date() <= day:
                j += 1
            if j >= 0 and state[j][1]:
                out[(day, iid)] = state[j][1]
    return out


# --- the score on each day -------------------------------------------------------------------------------------------------


def build(conn: psycopg.Connection, days: Sequence[date]) -> list[tuple[Any, ...]]:
    """(day, instrument_id, score, trend, participation, smart_money, quality) for every scored stock on each day."""
    days = sorted(days)
    if not days:
        return []
    names = {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT instrument_id, symbol FROM instrument WHERE asset_class='equity'"
        )
    }
    splits = pd.DataFrame(
        conn.execute(
            "SELECT instrument_id, ex_date FROM corporate_action WHERE kind IN ('split','bonus') AND status='ok' AND ex_date <= %s",
            (days[-1],),
        ).fetchall(),
        columns=["instrument_id", "ex_date"],
    )
    tech = technical_frame(load_bars(conn, days[0], days[-1]), splits, days)
    tech = tech[tech["instrument_id"].isin(names)]
    smart = smart_fields(conn, days)
    fund = fundamental_fields(conn, days, sorted(set(tech["instrument_id"])))
    out: list[tuple[Any, ...]] = []
    for day_key, part in tech.groupby("d"):
        day: date = day_key  # type: ignore[assignment]
        rows: list[dict[str, Any]] = []
        for rec in part.to_dict("records"):
            iid = int(rec["instrument_id"])
            row: dict[str, Any] = {
                "instrument_id": iid,
                **{
                    str(k): float(v)
                    for k, v in rec.items()
                    if k not in ("instrument_id", "d") and pd.notna(v)
                },
            }
            row.update(smart.get((day, names[iid]), {}))
            row.update(fund.get((day, iid), {}))
            rows.append(row)
        for r, s in zip(rows, score_universe(rows), strict=True):
            if s.composite is not None:
                parts = [s.components[k] for k in COMPONENTS]
                out.append(
                    (
                        day,
                        r["instrument_id"],
                        round(s.composite, 1),
                        *(None if v is None else round(v, 1) for v in parts),
                    )
                )
    return out


def store(conn: psycopg.Connection, rows: Sequence[tuple[Any, ...]]) -> int:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO stock_score_history (day, instrument_id, score, trend, participation, smart_money, quality) VALUES (%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT (day, instrument_id) DO UPDATE SET score=EXCLUDED.score, trend=EXCLUDED.trend, participation=EXCLUDED.participation,"
            " smart_money=EXCLUDED.smart_money, quality=EXCLUDED.quality",
            rows,
        )
    return len(rows)
