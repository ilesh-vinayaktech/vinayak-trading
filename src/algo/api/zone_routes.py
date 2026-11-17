# ruff: noqa: E501
"""The market zone for the dashboard (TODO 6.3): how fearful or greedy the market is today, what kind of market it is, the breadth behind that and a year of history.
Read-only, from `market_regime_daily` (built nightly by scripts/build_market_zone.py). Anyone who can read research can read it."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from algo.api.security import CurrentUser, PortalSettings, WConn
from algo.live.market_calendar import IST

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
