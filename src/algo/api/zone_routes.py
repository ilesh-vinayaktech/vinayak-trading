# ruff: noqa: E501
"""The market zone for the dashboard (TODO 6.3): how fearful or greedy the market is today, what kind of market it is, the breadth behind that and a year of history.
Read-only, from `market_regime_daily` (built nightly by scripts/build_market_zone.py). Anyone who can read research can read it."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from algo.api.security import CurrentUser, PortalSettings, WConn
from algo.live.market_calendar import IST
from algo.market import forecast, predict, sectors

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
