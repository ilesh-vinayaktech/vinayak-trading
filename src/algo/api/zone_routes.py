# ruff: noqa: E501
"""The market zone for the dashboard (TODO 6.3): how fearful or greedy the market is today, what kind of market it is, the breadth behind that and a year of history.
Read-only, from `market_regime_daily` (built nightly by scripts/build_market_zone.py). Anyone who can read research can read it."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from algo.api.security import CurrentUser, PortalSettings, WConn
from algo.live.market_calendar import IST
from algo.market import forecast, levels, predict, sectors

router = APIRouter(prefix="/api/market", tags=["market"])
HISTORY_DAYS = 260
NAMES = {
    "momentum": "Index trend against its 125-day average",
    "breadth": "Stocks above their 50-day average",
    "highs_lows": "New 52-week highs against lows",
    "volatility": "India VIX (calm is greed)",
    "advance_decline": "Advancers against decliners",
    "stocks_vs_bonds": "Stocks against government bonds",
    "risk_appetite": "High-beta against low-volatility stocks",
    "size_appetite": "Small caps against large caps",
}


def _st(request: Request) -> PortalSettings:
    st: PortalSettings = request.app.state.portal
    return st


def _num(v: Any) -> float | None:
    return None if v is None else float(v)


@router.get("/zone")
def zone(request: Request, who: CurrentUser, conn: WConn) -> dict[str, Any]:
    cols = "day, universe, advancers, decliners, unchanged, n50, above50, n200, above200, highs, lows, fear_greed, label, trend, volatility, components"
    row = conn.execute(
        f"SELECT {cols} FROM market_regime_daily ORDER BY day DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return {"latest": None, "history": [], "drivers": []}
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
    today = _st(request).clock.now().astimezone(IST).date()
    ranked = sorted(
        ((k, float(v)) for k, v in (comps or {}).items() if v is not None), key=lambda kv: kv[1]
    )
    history = conn.execute(
        "SELECT day, fear_greed, trend FROM market_regime_daily WHERE fear_greed IS NOT NULL ORDER BY day DESC LIMIT %s",
        (HISTORY_DAYS,),
    ).fetchall()
    return {
        "latest": {
            "day": day.isoformat(),
            "age_days": (today - day).days,
            "fear_greed": _num(fg),
            "label": label,
            "trend": trend,
            "volatility": vol,
            "universe": universe,
            "advancers": adv,
            "decliners": dec,
            "unchanged": unch,
            "pct_above_50": None if not n50 else round(100.0 * a50 / n50, 1),
            "pct_above_200": None if not n200 else round(100.0 * a200 / n200, 1),
            "highs": highs,
            "lows": lows,
        },
        "drivers": [
            {"key": k, "name": NAMES[k], "score": round(v, 1)} for k, v in reversed(ranked)
        ],
        "history": [
            {"day": d.isoformat(), "fear_greed": _num(f), "trend": t}
            for d, f, t in reversed(history)
        ],
    }


@router.get("/sectors")
def sector_rotation(who: CurrentUser, conn: WConn) -> dict[str, Any]:
    """Where money is flowing: each sector index's returns, strength against the Nifty 500 and rotation quadrant, strongest first."""
    dates, bench, series = sectors.load(conn)
    rows = sorted(sectors.rotation(series, bench), key=lambda r: -r.score)
    return {
        "as_of": dates[-1].isoformat() if dates and rows else None,
        "benchmark": sectors.BENCHMARK,
        "sectors": [
            {
                "name": r.name, "score": round(r.score, 1), "close": round(r.close, 2), "ret_1d": r.ret_1d, "ret_5d": r.ret_5d,
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


@router.get("/forecast")
def forecast_view(request: Request, who: CurrentUser, conn: WConn) -> dict[str, Any]:
    """Tomorrow and next week for the market and each sector: the probability of UP with the evidence behind it, how this model has done against plain guessing
    (walk-forward history, and live once it has outcomes) and its biggest recent misses. Built nightly by scripts/build_predictions.py."""
    latest = conn.execute("SELECT max(as_of) FROM prediction_log WHERE live").fetchone()
    day = latest[0] if latest else None
    if day is None:
        return {"as_of": None, "market": [], "sectors": [], "record": [], "misses": []}
    rows = conn.execute(
        "SELECT subject, horizon_days, p_up, evidence FROM prediction_log WHERE live AND as_of=%s ORDER BY subject, horizon_days",
        (day,),
    ).fetchall()
    by: dict[str, dict[int, tuple[float, list[Any]]]] = {}
    for subject, h, p, ev in rows:
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
    for h in forecast.HORIZONS:
        for live in (False, True):
            s = _skill(forecast.track_record(conn, "MARKET", h, live))
            if s:
                record.append({"subject": "Market", "horizon_days": h, "live": live, **s})
    misses = [
        {"as_of": d.isoformat(), "p_up": float(p), "realized": float(r), "went_up": bool(u), "evidence": ev}
        for d, p, r, u, ev in conn.execute(
            "SELECT as_of, p_up, realized, outcome_up, evidence FROM prediction_log WHERE subject='MARKET' AND horizon_days=1 AND outcome_up IS NOT NULL"
            " AND ((p_up > 0.5 AND NOT outcome_up) OR (p_up < 0.5 AND outcome_up)) ORDER BY abs(p_up - 0.5) DESC, as_of DESC LIMIT 8"
        )
    ]  # fmt: skip
    return {
        "as_of": day.isoformat(),
        "market": market,
        "sectors": sect,
        "record": record,
        "misses": misses,
        "labels": predict.LABELS,
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


@router.get("/news")
def news_view(request: Request, who: CurrentUser, conn: WConn) -> dict[str, Any]:
    """Recent market headlines with their sentiment, the mood by day over the last week and the stocks named most in the last three days.
    The sentiment is a crude word list that has not been checked against what markets did next: a gauge to look at, not a signal."""
    now = _st(request).clock.now()
    items = [
        {"title": t, "url": u, "source": s, "published_at": p.isoformat(), "sentiment": None if v is None else float(v), "symbols": sy}
        for t, u, s, p, v, sy in conn.execute(
            "SELECT title, url, source, published_at, sentiment, symbols FROM news_item ORDER BY published_at DESC LIMIT 30"
        )
    ]  # fmt: skip
    mood = [
        {"day": d.isoformat(), "avg": float(a), "n": n, "positive": pos, "negative": neg}
        for d, a, n, pos, neg in conn.execute(
            "SELECT (published_at AT TIME ZONE 'Asia/Kolkata')::date d, avg(sentiment), count(sentiment), count(*) FILTER (WHERE sentiment > 0.15), count(*) FILTER (WHERE sentiment < -0.15)"
            " FROM news_item WHERE sentiment IS NOT NULL AND published_at > %s::timestamptz - interval '8 days' GROUP BY 1 ORDER BY 1", (now,)
        )
    ]  # fmt: skip
    stocks = [
        {"symbol": sym, "mentions": n, "avg": float(a)}
        for sym, n, a in conn.execute(
            "SELECT sym, count(*), coalesce(avg(sentiment), 0) FROM news_item, unnest(symbols) sym WHERE published_at > %s::timestamptz - interval '3 days' GROUP BY sym ORDER BY count(*) DESC, sym LIMIT 12", (now,)
        )
    ]  # fmt: skip
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
