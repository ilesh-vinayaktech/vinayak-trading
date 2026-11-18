# ruff: noqa: E501
"""The market zone for the dashboard (TODO 6.3): how fearful or greedy the market is today, what kind of market it is, the breadth behind that and a year of history.
Read-only, from `market_regime_daily` (built nightly by scripts/build_market_zone.py). Anyone who can read research can read it."""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from algo.api.security import CurrentUser, PortalSettings, WConn
from algo.data import global_markets, news_laya
from algo.data import index_members as index_members_data
from algo.data import sectors as sectors_data
from algo.live.index_store import read_quotes
from algo.live.market_calendar import IST
from algo.market import forecast, levels, live_zone, performance, predict, sectors, stock_notes

router = APIRouter(prefix="/api/market", tags=["market"])
HISTORY_DAYS = 10_000  # every stored day; the page picks 1 year, 3 years or all
NAMES = {
    "momentum": "Index trend against its 125-day average",
    "breadth": "Stocks above their 50-day average",
    "highs_lows": "New 52-week highs against lows",
    "volatility": "India VIX (calm is greed)",
    "advance_decline": "Advancers against decliners",
    "stocks_vs_bonds": "Stocks against government bonds",
    "risk_appetite": "High-beta against low-volatility stocks",
    "size_appetite": "Small caps against large caps",
    "gold_demand": "Gold against stocks (gold winning is fear)",
    "fii_positioning": "FII net position in index futures",
}


def _st(request: Request) -> PortalSettings:
    st: PortalSettings = request.app.state.portal
    return st


def _num(v: Any) -> float | None:
    return None if v is None else float(v)


LIVE_TTL = timedelta(
    seconds=30
)  # the live reading is worked out at most this often, however many people have the page open
_live_lock = threading.Lock()
_notes_lock = threading.Lock()


def _live(
    request: Request, conn: Any, now: datetime, today: date
) -> tuple[live_zone.LiveZone | None, datetime | None]:
    """Today's zone from live prices and when it was worked out, or (None, None) (the snapshot stays). Cached on the app for LIVE_TTL; a failure never breaks the page."""
    with _live_lock:
        cache: dict[str, Any] = request.app.state.__dict__.setdefault(
            "live_zone_cache", {"at": None, "day": None, "value": None}
        )
        at = cache["at"]
        if at is not None and cache["day"] == today and now - at < LIVE_TTL:
            return cache["value"], at
        try:
            value = live_zone.live_zone(conn, today, HISTORY_DAYS)
        except Exception:  # a broken live reading must not take the zone page down; the nightly snapshot is still right
            logging.getLogger(__name__).exception("live market zone failed")
            value = None
        cache.update(at=now, day=today, value=value)
        return value, now


@router.get("/zone")
def zone(request: Request, who: CurrentUser, conn: WConn) -> dict[str, Any]:
    cols = "day, universe, advancers, decliners, unchanged, n50, above50, n200, above200, highs, lows, fear_greed, label, trend, volatility, components"
    row = conn.execute(
        f"SELECT {cols} FROM market_regime_daily ORDER BY day DESC LIMIT 1"
    ).fetchone()
    now = _st(request).clock.now()
    today = now.astimezone(IST).date()
    live, worked_out = _live(request, conn, now, today)
    if row is None and live is None:
        return {"latest": None, "history": [], "drivers": []}
    if live is not None:  # today's reading from live prices, scored against the same history
        b = live.breadth
        comps = live.components
        latest: dict[str, Any] = {
            "day": today.isoformat(), "age_days": 0, "live": True, "as_of": None if worked_out is None else worked_out.isoformat(),
            "fear_greed": None if live.fear_greed is None else round(live.fear_greed, 2), "label": live.label, "trend": live.trend, "volatility": live.volatility,
            "universe": b.universe, "advancers": b.advancers, "decliners": b.decliners, "unchanged": b.unchanged,
            "pct_above_50": None if b.pct_above_50 is None else round(b.pct_above_50, 1),
            "pct_above_200": None if b.pct_above_200 is None else round(b.pct_above_200, 1),
            "highs": b.highs, "lows": b.lows,
        }  # fmt: skip
        history = [{"day": d.isoformat(), "fear_greed": f, "trend": t} for d, f, t in live.history]
    else:
        assert row is not None
        (
            day,
            universe,
            adv,
            dec,
            unch,
            n50,
            a50,
            n200,
            a200,
            highs,
            lows,
            fg,
            label,
            trend,
            vol,
            comps,
        ) = row
        latest = {
            "day": day.isoformat(), "age_days": (today - day).days, "live": False, "as_of": None,
            "fear_greed": _num(fg), "label": label, "trend": trend, "volatility": vol, "universe": universe,
            "advancers": adv, "decliners": dec, "unchanged": unch,
            "pct_above_50": None if not n50 else round(100.0 * a50 / n50, 1),
            "pct_above_200": None if not n200 else round(100.0 * a200 / n200, 1),
            "highs": highs, "lows": lows,
        }  # fmt: skip
        stored = conn.execute(
            "SELECT day, fear_greed, trend FROM market_regime_daily WHERE fear_greed IS NOT NULL ORDER BY day DESC LIMIT %s", (HISTORY_DAYS,)
        ).fetchall()  # fmt: skip
        history = [
            {"day": d.isoformat(), "fear_greed": _num(f), "trend": t}
            for d, f, t in reversed(stored)
        ]
    reading = {} if live is None else live.readings
    ranked = sorted(
        ((k, float(v)) for k, v in (comps or {}).items() if v is not None), key=lambda kv: kv[1]
    )
    return {
        "latest": latest,
        "drivers": [
            {"key": k, "name": NAMES[k], "score": round(v, 1), "reading": reading.get(k)}
            for k, v in reversed(ranked)
        ],
        "history": history,
    }


@router.get("/zone/performance")
def zone_performance(who: CurrentUser, conn: WConn) -> dict[str, Any]:
    """Nifty 50 against the zone history: its close for each day of the history window, and its average return after each zone over all stored days."""
    scored = [
        (d, float(f))
        for d, f in conn.execute(
            "SELECT day, fear_greed FROM market_regime_daily WHERE fear_greed IS NOT NULL ORDER BY day"
        ).fetchall()
    ]
    closes = [
        (d, float(c))
        for d, c in conn.execute(
            "SELECT trade_date, close FROM index_bar_1d WHERE exchange='NSE' AND symbol='NIFTY 50' ORDER BY trade_date"
        ).fetchall()
    ]
    window = {d for d, _ in scored[-HISTORY_DAYS:]}
    return {
        "nifty": [{"day": d.isoformat(), "close": c} for d, c in closes if d in window],
        "zones": performance.by_zone(scored, closes),
    }


@router.get("/sectors")
def sector_rotation(request: Request, who: CurrentUser, conn: WConn) -> dict[str, Any]:
    """Where money is flowing: each sector index's returns, strength against the Nifty 500 and rotation quadrant, strongest first."""
    dates, bench, series = sectors.load(conn)
    rows = sorted(sectors.rotation(series, bench), key=lambda r: -r.score)
    symbol_of = {name: sym for sym, name in sectors.SECTORS.items()}
    today = datetime.combine(_st(request).clock.now().astimezone(IST).date(), time(0), IST)
    quotes = read_quotes(
        conn, list(sectors.SECTORS), today
    )  # the sector index's live level and change from yesterday's close, while the feed runs

    def now_of(name: str) -> dict[str, Any] | None:
        q = quotes.get(symbol_of.get(name, ""))
        if q is None or not q[1]:
            return None
        return {
            "ltp": round(q[0], 2),
            "prev_close": round(q[1], 2),
            "change_pct": 100.0 * (q[0] - q[1]) / q[1],
            "as_of": q[2].isoformat(),
        }

    return {
        "as_of": dates[-1].isoformat() if dates and rows else None,
        "benchmark": sectors.BENCHMARK,
        "sectors": [
            {
                "name": r.name, "symbol": symbol_of.get(r.name), "now": now_of(r.name), "score": round(r.score, 1), "close": round(r.close, 2), "ret_1d": r.ret_1d, "ret_5d": r.ret_5d,
                "ret_21d": r.ret_21d, "ret_63d": r.ret_63d, "ret_252d": r.ret_252d, "above_50": r.above_50, "above_200": r.above_200,
                "rs_ratio": round(r.rs_ratio, 2), "rs_momentum": round(r.rs_momentum, 2), "quadrant": r.quadrant,
            }
            for r in rows
        ],
    }  # fmt: skip


def _skill(s: Any) -> dict[str, Any] | None:
    if s is None:
        return None
    return {
        "n": s.n, "hit_rate": s.hit_rate, "base_rate": s.base_rate, "base_hit": s.base_hit, "brier_skill": s.brier_skill,
        "beats_guessing": s.brier_skill > 0.005 and s.hit_rate > s.base_hit,
        "calibration": [{"predicted": a, "actual": b, "n": n} for a, b, n in s.calibration],
    }  # fmt: skip


def _live_moves(request: Request, conn: Any) -> dict[str, Any]:
    """What the market and each sector are doing today, from the live index quotes (empty while the feed is off): the change from yesterday's close, in %."""
    today = datetime.combine(_st(request).clock.now().astimezone(IST).date(), time(0), IST)
    quotes = read_quotes(conn, ["NIFTY 500", *sectors.SECTORS], today)

    def change(symbol: str) -> float | None:
        q = quotes.get(symbol)
        return None if q is None or not q[1] else 100.0 * (q[0] - q[1]) / q[1]

    as_of = quotes.get("NIFTY 500")
    return {
        "market_change_pct": change("NIFTY 500"),
        "as_of": None if as_of is None else as_of[2].isoformat(),
        "sectors": {
            name: c for sym, name in sectors.SECTORS.items() if (c := change(sym)) is not None
        },
    }


def _overnight(conn: Any, as_of: date) -> dict[str, Any]:
    """What the world did overnight before the session the forecast is for (the next weekday after `as_of`): the US sessions, and what GIFT Nifty indicated at 08:45."""
    target = as_of + timedelta(days=1)
    while target.weekday() >= 5:
        target += timedelta(days=1)
    us = {
        k: global_markets.last_session_return(global_markets.series(conn, s), target)
        for k, s in (("sp", "SP500"), ("nq", "NASDAQ"), ("vix", "VIXUS"))
    }
    gift = dict(global_markets.series(conn, global_markets.GIFT))
    close = conn.execute(
        "SELECT close FROM index_bar_1d WHERE exchange='NSE' AND symbol='NIFTY 50' AND trade_date=%s",
        (as_of,),
    ).fetchone()
    gap = 100.0 * (gift[target] / float(close[0]) - 1) if target in gift and close else None
    closes = {
        d: float(c)
        for d, c in conn.execute(
            "SELECT trade_date, close FROM index_bar_1d WHERE exchange='NSE' AND symbol='NIFTY 500' ORDER BY trade_date"
        )
    }
    n50 = {
        d: float(c)
        for d, c in conn.execute(
            "SELECT trade_date, close FROM index_bar_1d WHERE exchange='NSE' AND symbol='NIFTY 50' ORDER BY trade_date"
        )
    }
    days = sorted(closes)
    pairs = [
        (100.0 * (g / n50[prev] - 1), 100.0 * (closes[d] / closes[prev] - 1))
        for prev, d in zip(days, days[1:], strict=False)
        if (g := gift.get(d)) is not None and prev in n50
    ]
    return {
        "for_day": target.isoformat(),
        **us,
        "gift_gap_pct": gap,
        "gift_history": performance.gift_buckets(pairs),
    }


@router.get("/forecast")
def forecast_view(request: Request, who: CurrentUser, conn: WConn) -> dict[str, Any]:
    """Tomorrow and next week for the market and each sector: the probability of UP with the evidence behind it, how this model has done against plain guessing
    (walk-forward history, and live once it has outcomes) and its biggest recent misses. Built nightly by scripts/build_predictions.py."""
    versions = [forecast.version(q) for q in forecast.PRODUCTS]
    latest = conn.execute(
        "SELECT max(as_of) FROM prediction_log WHERE live AND model_version = ANY(%s)", (versions,)
    ).fetchone()
    day = latest[0] if latest else None
    if day is None:
        return {
            "as_of": None,
            "market": [],
            "sectors": [],
            "record": [],
            "misses": [],
            "today": None,
            "overnight": None,
        }
    rows = conn.execute(
        "SELECT subject, horizon_days, p_up, evidence, model_version FROM prediction_log WHERE live AND as_of=%s AND model_version = ANY(%s) ORDER BY subject, horizon_days",
        (day, versions),
    ).fetchall()
    morning = forecast.version("morning")
    product = (
        "morning" if any(r[4] == morning for r in rows if r[0] == "MARKET") else "night"
    )  # the morning forecast replaces the night's on the page once it exists
    by: dict[str, dict[int, tuple[float, list[Any]]]] = {}
    for subject, h, p, ev, _v in sorted(
        rows, key=lambda r: r[4] == morning
    ):  # the morning rows come last and win
        by.setdefault(subject, {})[h] = (float(p), ev)
    market = [
        {"horizon_days": h, "p_up": p, "evidence": ev}
        for h, (p, ev) in sorted(by.get("MARKET", {}).items())
    ]
    sect = sorted(
        (
            {"name": s, "p_1d": v.get(1, (None, []))[0], "p_5d": v.get(5, (None, []))[0], "evidence": v.get(1, (None, []))[1][:2]}
            for s, v in by.items() if s != "MARKET"
        ),
        key=lambda r: -(r["p_1d"] if isinstance(r["p_1d"], float) else 0.0),
    )  # fmt: skip
    record = []
    for q in forecast.PRODUCTS:
        for h in forecast.HORIZONS:
            for live in (False, True):
                s = _skill(forecast.track_record(conn, "MARKET", h, live, product=q))
                if s:
                    record.append(
                        {"subject": "Market", "product": q, "horizon_days": h, "live": live, **s}
                    )
    misses = [
        {"as_of": d.isoformat(), "p_up": float(p), "realized": float(r), "went_up": bool(u), "evidence": ev}
        for d, p, r, u, ev in conn.execute(
            "SELECT as_of, p_up, realized, outcome_up, evidence FROM prediction_log WHERE subject='MARKET' AND horizon_days=1 AND outcome_up IS NOT NULL"
            " AND model_version=%s AND ((p_up > 0.5 AND NOT outcome_up) OR (p_up < 0.5 AND outcome_up)) ORDER BY abs(p_up - 0.5) DESC, as_of DESC LIMIT 8",
            (forecast.version(product),),
        )
    ]  # fmt: skip
    return {
        "as_of": day.isoformat(),
        "product": product,  # night | morning: which forecast the page is showing
        "cutoff": forecast.CUTOFFS[product],
        "market": market,
        "sectors": sect,
        "record": record,
        "misses": misses,
        "labels": predict.LABELS,
        "overnight": _overnight(conn, day),
        "today": _live_moves(
            request, conn
        ),  # the forecast was made after the close of `as_of`: the next session is the one now being traded
    }


@router.get("/levels")
def levels_view(symbol: str, request: Request, who: CurrentUser, conn: WConn) -> dict[str, Any]:
    """Support and resistance, breakout status and the volume-at-price and return histograms for one stock, from its daily bars since its latest split or bonus."""
    sym = symbol.strip().upper()
    row = conn.execute(
        "SELECT instrument_id, name FROM instrument WHERE asset_class='equity' AND symbol=%s AND delisted_on IS NULL",
        (sym,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"no listed stock {sym}")
    iid, name = row
    split = conn.execute(
        "SELECT max(ex_date) FROM corporate_action WHERE instrument_id=%s AND kind IN ('split','bonus') AND status='ok' AND ex_date <= current_date",
        (iid,),
    ).fetchone()
    cut = split[0] if split else None
    bars = conn.execute(
        "SELECT (ts AT TIME ZONE 'Asia/Kolkata')::date, high::float8, low::float8, close::float8, volume::float8, CASE WHEN series='EQ' THEN delivery_qty::float8 END FROM ("
        " SELECT DISTINCT ON (ts) * FROM bar_1d WHERE instrument_id=%s AND source='nse' ORDER BY ts, dataset_version DESC) x"
        " WHERE (ts AT TIME ZONE 'Asia/Kolkata')::date >= coalesce(%s::date, '1900-01-01') ORDER BY ts DESC LIMIT 400", (iid, cut)
    ).fetchall()[::-1]  # fmt: skip
    if not bars:
        raise HTTPException(404, f"no daily bars for {sym}")
    days = [b[0] for b in bars]
    high, low, close, vol = ([b[i] for b in bars] for i in (1, 2, 3, 4))
    pct = [100 * b[5] / b[4] if b[5] is not None and b[4] > 0 else None for b in bars]
    norm = [p for p in pct[-21:-1] if p is not None]
    deliv = (
        pct[-1] / (sum(norm) / len(norm))
        if pct[-1] is not None and norm and sum(norm) > 0
        else None
    )
    out = levels.analyse(high, low, close, vol, deliv)
    if out is None:
        return {
            "symbol": sym,
            "name": name,
            "as_of": days[-1].isoformat(),
            "enough_history": False,
            "bars": len(bars),
        }
    shown = slice(-250, None)
    return {
        "symbol": sym, "name": name, "as_of": days[-1].isoformat(), "enough_history": True, "since_split": cut.isoformat() if cut else None,
        **out, "series": [{"day": d.isoformat(), "close": c} for d, c in zip(days[shown], close[shown], strict=True)],
    }  # fmt: skip


def _news_item(
    t: str, u: str, s: str, p: datetime, v: Any, sy: list[str], lv: Any, lc: Any
) -> dict[str, Any]:
    label, value, model = news_laya.reading(
        None if v is None else float(v), None if lv is None else float(lv)
    )
    return {
        "title": t, "url": u, "source": s, "published_at": p.isoformat(), "symbols": sy,
        "sentiment": None if v is None else float(v),  # the keyword reading, kept for comparison
        "laya": None if lv is None else float(lv), "laya_confidence": None if lc is None else float(lc),
        "reading": label, "reading_value": value, "reading_model": model,  # the one to show: Laya's where it has one
    }  # fmt: skip


NEWS_COLUMNS = (
    "title, url, source, published_at, sentiment, symbols, laya_sentiment, laya_confidence"
)


@router.get("/news")
def news_view(
    request: Request, who: CurrentUser, conn: WConn, symbol: str | None = None
) -> dict[str, Any]:
    """Recent market headlines, each with one reading (Laya's where it has scored the headline, else the keyword list's, and which), the mood by day over the last week and the stocks
    named most in the last three days. With `symbol`, only the headlines that name that stock (the last 30 days, newest first) and no mood or ranking. Neither reading has been shown to
    predict returns: a gauge to look at, not a signal."""
    now = _st(request).clock.now()
    if symbol is not None:
        sym = symbol.strip().upper()
        rows = conn.execute(
            f"SELECT {NEWS_COLUMNS} FROM news_item WHERE %s = ANY(symbols) AND published_at > %s::timestamptz - interval '30 days' ORDER BY published_at DESC LIMIT 30", (sym, now)
        ).fetchall()  # fmt: skip
        return {
            "items": [_news_item(t, u, s, p, v, sy, lv, lc) for t, u, s, p, v, sy, lv, lc in rows],
            "mood": [],
            "stocks": [],
        }
    rows = conn.execute(
        f"SELECT {NEWS_COLUMNS} FROM news_item WHERE published_at > %s::timestamptz - interval '8 days' ORDER BY published_at DESC",
        (now,),
    ).fetchall()
    items = [
        _news_item(t, u, s, p, v, sy, lv, lc)
        for t, u, s, p, v, sy, lv, lc in conn.execute(
            f"SELECT {NEWS_COLUMNS} FROM news_item ORDER BY published_at DESC LIMIT 30"
        )
    ]
    days: dict[date, list[tuple[str, float]]] = {}
    named: dict[str, list[float]] = {}
    for row in rows:
        p, v, sy, lv = row[3], row[4], row[5], row[6]
        label, value, _ = news_laya.reading(
            None if v is None else float(v), None if lv is None else float(lv)
        )
        if label is None or value is None:
            continue
        days.setdefault(p.astimezone(IST).date(), []).append((label, value))
        if p > now - timedelta(days=3):
            for sym_ in sy:
                named.setdefault(sym_, []).append(value)
    mood = [
        {"day": d.isoformat(), "avg": sum(v for _, v in xs) / len(xs), "n": len(xs), "positive": sum(1 for lab, _ in xs if lab == "positive"), "negative": sum(1 for lab, _ in xs if lab == "negative")}
        for d, xs in sorted(days.items())
    ]  # fmt: skip
    ranked = sorted(named.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:8]
    stocks = [{"symbol": k, "mentions": len(v), "avg": sum(v) / len(v)} for k, v in ranked]
    return {"items": items, "mood": mood, "stocks": stocks}


@router.get("/score")
def score_view(symbol: str, request: Request, who: CurrentUser, conn: WConn) -> dict[str, Any]:
    """One stock's swing score today with its four parts, the setup flags and reasons, and its score history (weekly, then daily from the nightly job)."""
    sym = symbol.strip().upper()
    row = conn.execute(
        "SELECT instrument_id, name FROM instrument WHERE asset_class='equity' AND symbol=%s AND delisted_on IS NULL",
        (sym,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"no listed stock {sym}")
    iid, name = row
    snap = conn.execute(
        "SELECT row FROM screener_snapshot WHERE instrument_id=%s", (iid,)
    ).fetchone()
    today = snap[0] if snap else {}
    hist = [
        {"day": d.isoformat(), "score": float(s)}
        for d, s in conn.execute(
            "SELECT day, score FROM (SELECT day, score FROM stock_score_history WHERE instrument_id=%s ORDER BY day DESC LIMIT 160) x ORDER BY day", (iid,)
        )
    ]  # fmt: skip
    comps = {
        k: _num(today.get(f"score_{k}"))
        for k in ("trend", "participation", "smart_money", "quality")
    }
    return {
        "symbol": sym, "name": name, "as_of": today.get("as_of"), "score": _num(today.get("score")), "components": comps,
        "setup": today.get("setup"), "why": today.get("score_why"), "history": hist,
        "scored": today.get("score") is not None,
    }  # fmt: skip


@router.get("/industries")
def industries_view(request: Request, who: CurrentUser, conn: WConn) -> dict[str, Any]:
    """Breadth inside each industry group of the Nifty 500 (sectors as NSE lists them): how many stocks are above their 50 and 200-day averages and rose today, the median
    1-month move, the average swing score and the best-scored names, from today's screener table. Only stocks with a sector are counted."""
    sector_of = sectors_data.sectors_on(conn, _st(request).clock.now().astimezone(IST).date())
    rows = conn.execute("SELECT instrument_id, row FROM screener_snapshot").fetchall()
    groups: dict[str, list[dict[str, Any]]] = {}
    for iid, r in rows:
        sec = sector_of.get(int(iid))
        if sec is not None:
            groups.setdefault(sec, []).append(
                {**r, "_id": int(iid)}
            )  # the id travels with the row: the stored JSON need not carry it
    today = datetime.combine(_st(request).clock.now().astimezone(IST).date(), time(0), IST)
    live: dict[int, float] = {  # each stock's change today against yesterday's close, from the live quotes
        int(i): float((ltp - prev) / prev * 100)
        for i, ltp, prev in conn.execute(
            "SELECT instrument_id, ltp, prev_close FROM live_quote WHERE updated_at >= %s AND prev_close > 0 AND ltp > 0", (today,)
        )
    }  # fmt: skip
    out = []
    for name, rs in groups.items():
        moves = [live[r["_id"]] for r in rs if r["_id"] in live]

        def share(key: str, test: Any, rs: list[dict[str, Any]] = rs) -> float | None:
            have = [_num(r.get(key)) for r in rs if r.get(key) is not None]
            return (
                None
                if not have
                else 100.0 * sum(1 for v in have if v is not None and test(v)) / len(have)
            )

        m1 = sorted(v for v in (_num(r.get("chg_1m")) for r in rs) if v is not None)
        scored = [(float(r["score"]), r["symbol"]) for r in rs if r.get("score") is not None]
        out.append({
            "name": name, "stocks": len(rs), "above_50": share("price_vs_sma50", lambda v: v > 0), "above_200": share("price_vs_sma200", lambda v: v > 0),
            "up_today": share("chg_1d", lambda v: v > 0), "median_1m": m1[len(m1) // 2] if m1 else None,
            "avg_score": sum(s for s, _ in scored) / len(scored) if scored else None, "scored": len(scored),
            "top": [sym for _, sym in sorted(scored, reverse=True)[:3]],
            "live_change": sum(moves) / len(moves) if moves else None, "live_up": sum(1 for m in moves if m > 0), "live_down": sum(1 for m in moves if m < 0),
        })  # fmt: skip
    out.sort(key=lambda g: -float(g["avg_score"]) if isinstance(g["avg_score"], float) else 1.0)
    return {"as_of": max((r["as_of"] for _, r in rows), default=None), "industries": out}


NOTES_TTL = timedelta(seconds=60)
MAX_NOTE_IDS = stock_notes.MAX_IDS


@router.get("/notes")
def notes_view(ids: str, request: Request, who: CurrentUser, conn: WConn) -> dict[str, Any]:
    """Short facts worth noticing about each stock (`ids`: comma separated instrument ids, at most 60): a breakout or a stock about to break, an inside bar, a volume or delivery
    surge, a new 52-week high, news, an upcoming ex-date, deals and insider trades. Facts about the chart and the tape, not signals. Worked out at most once a minute per list."""
    try:
        want = sorted({int(x) for x in ids.split(",") if x.strip()})[:MAX_NOTE_IDS]
    except ValueError:
        raise HTTPException(400, "ids must be integers separated by commas") from None
    now = _st(request).clock.now()
    with _notes_lock:
        cache: dict[tuple[int, ...], tuple[datetime, dict[int, list[Any]]]] = (
            request.app.state.__dict__.setdefault("notes_cache", {})
        )
        key = tuple(want)
        hit = cache.get(key)
        if hit is None or now - hit[0] >= NOTES_TTL:
            if len(cache) > 200:
                cache.clear()
            hit = cache[key] = (now, stock_notes.notes_for(conn, want, now))
    return {
        "as_of": hit[0].isoformat(),
        "notes": {
            str(i): [
                {"kind": n.kind, "tone": n.tone, "text": n.text, "rank": n.rank, "detail": n.detail}
                for n in ns
            ]
            for i, ns in hit[1].items()
        },
    }


@router.get("/index-members")
def index_members(
    request: Request,
    who: CurrentUser,
    conn: WConn,
    symbol: str | None = None,
    industry: str | None = None,
) -> dict[str, Any]:
    """The stocks inside an index (`symbol`, from NSE's official list) or inside one of our industry groups (`industry`), matched to our instruments. Their prices come from
    the live quotes route; an index with no stored list (Sensex, India VIX, ...) is a 404 that says so."""
    if (symbol is None) == (industry is None):
        raise HTTPException(400, "give either symbol or industry")
    found: list[tuple[int, str, str | None]]
    if industry is not None:
        sector_of = sectors_data.sectors_on(conn, _st(request).clock.now().astimezone(IST).date())
        ids = [i for i, sec in sector_of.items() if sec == industry]
        if not ids:
            raise HTTPException(404, f"no industry {industry}")
        found = conn.execute(
            "SELECT instrument_id, symbol, name FROM instrument WHERE instrument_id = ANY(%s) ORDER BY symbol",
            (ids,),
        ).fetchall()
        return {"kind": "industry", "symbol": None, "name": industry, "as_of": None, "unmatched": 0,
                "members": [{"instrument_id": i, "symbol": s, "name": n, "industry": industry} for i, s, n in found]}  # fmt: skip
    assert symbol is not None
    lake = getattr(request.app.state, "lake", Path("data/lake"))
    listed = index_members_data.members(lake, symbol)
    if listed is None:
        raise HTTPException(404, f"no constituent list stored for {symbol}")
    as_of, rows = listed
    by_isin = {
        isin: (i, s, n)
        for i, isin, s, n in conn.execute(
            "SELECT instrument_id, isin, symbol, name FROM instrument WHERE asset_class='equity' AND isin = ANY(%s)",
            ([m.isin for m in rows],),
        )
    }
    out, unmatched = [], 0
    for m in rows:
        hit = by_isin.get(m.isin)
        if hit is None:
            unmatched += 1
            continue
        out.append(
            {
                "instrument_id": hit[0],
                "symbol": hit[1],
                "name": hit[2] or m.name,
                "industry": m.industry,
            }
        )
    return {
        "kind": "index",
        "symbol": symbol,
        "name": sectors.SECTORS.get(symbol, symbol.title()),
        "as_of": as_of.isoformat(),
        "unmatched": unmatched,
        "members": out,
    }


MAX_WATCHED = 50


class WatchBody(BaseModel):
    symbol: str = Field(min_length=1, max_length=30)


@router.get("/watchlist")
def watchlist_view(who: CurrentUser, conn: WConn) -> dict[str, Any]:
    """The caller's watched stocks, newest first. Their score and levels come from the per-stock routes."""
    rows = conn.execute(
        "SELECT i.instrument_id, i.symbol, i.name, w.added_at, w.added_price FROM watchlist w JOIN instrument i USING (instrument_id) WHERE w.user_id=%s ORDER BY w.added_at DESC, i.symbol",
        (who.session.user_id,),
    ).fetchall()
    return {
        "items": [
            {"instrument_id": a, "symbol": s, "name": n, "added_at": at.isoformat(), "added_price": None if p is None else format(p.normalize(), "f")}
            for a, s, n, at, p in rows
        ]
    }  # fmt: skip


@router.post("/watchlist")
def watchlist_add(
    body: WatchBody, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, bool]:
    sym = body.symbol.strip().upper()
    row = conn.execute(
        "SELECT instrument_id FROM instrument WHERE asset_class='equity' AND symbol=%s AND delisted_on IS NULL",
        (sym,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"no listed stock {sym}")
    held = conn.execute(
        "SELECT count(*) FROM watchlist WHERE user_id=%s", (who.session.user_id,)
    ).fetchone()
    if held and held[0] >= MAX_WATCHED:
        raise HTTPException(400, f"the watchlist holds at most {MAX_WATCHED} stocks")
    price = conn.execute(  # the live price if the feed has quoted it, else the last daily close
        "SELECT coalesce((SELECT ltp FROM live_quote WHERE instrument_id=%s),"
        " (SELECT close FROM bar_1d WHERE instrument_id=%s AND source='nse' ORDER BY ts DESC, dataset_version DESC LIMIT 1))",
        (row[0], row[0]),
    ).fetchone()
    conn.execute(
        "INSERT INTO watchlist (user_id, instrument_id, added_at, added_price) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
        (who.session.user_id, row[0], _st(request).clock.now(), price[0] if price else None),
    )
    return {"ok": True}


@router.delete("/watchlist/{instrument_id}")
def watchlist_remove(instrument_id: int, who: CurrentUser, conn: WConn) -> dict[str, bool]:
    conn.execute(
        "DELETE FROM watchlist WHERE user_id=%s AND instrument_id=%s",
        (who.session.user_id, instrument_id),
    )
    return {"ok": True}
