# ruff: noqa: E501
"""Buy-zone / sell-zone study (2026-11-19). RESEARCH ONLY. FROZEN BEFORE THE FIRST RUN; nothing below was tuned.

Question (owner): is "this stock is in a buy zone" / "in a sell zone" worth showing? A zone is a location, not a promise: does buying there beat the market after costs?
Zones are the repo's own definitions (algo.market.levels: swing pivots k=5, merged within 1.5%, NEAR 1.5%, BREAK_MARGIN 0.5%), worked out at the close of T from bars up to T:
  BUY zone   nearest support (level below the close) has >= 2 touches AND close is within [support*(1-0.5%), support*(1+1.5%)]   ("Testing support")
  SELL zone  nearest resistance (level above the close) has >= 2 touches AND close is within [resistance*(1-1.5%), resistance*(1+0.5%)] ("Testing resistance")
  Universe   liquid stocks (20-day mean turnover >= Rs 5 crore), EQ series, outside the +-25/+22 session window of a price-changing corporate action. Signals are sampled every 5th session so outcomes do not overlap.
  Trade      buy at the OPEN of T+1, sell at the CLOSE of T+5 (5 sessions). Excess = trade return minus the mean of the same open-to-close return over ALL liquid stocks on that date.
  Costs      repo DELIVERY schedule round trip + slippage 10 bps per side (primary). The sell zone is a caution, not a short: it is judged on gross excess only.
SUCCESS RULE (fixed now). BUY: net excess per signal-date (mean of per-date means) > 0 with the 95% CI over dates above 0 AND positive in at least 4 of the 5 years 2020-2024. SELL: gross excess < 0 with the CI below 0 AND negative in at least 4 of 5 years.
Fewer than 300 zone signals = INCONCLUSIVE. Anything else = FAIL. Secondary views (uptrend-only, "inside its range" control) are printed and cannot rescue a FAIL.
Data: bars strictly before 2025-01-01 (the protected holdout, config/research_holdout.json, is not read). Dividends are not added back (same for zone and market).
usage: study_zones.py [--db URL]"""

import argparse
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd
import psycopg
from study_common import BARS, book_from_db  # noqa: E402,I001

from algo.backtest.costs.calculator import compute_charges
from algo.market import levels as lv
from algo.research import next_session_features as ns

END, FIRST, HOLD, STEP, LOOK, MINTOUCH, SLIP = "2025-01-01", "2019-11-01", 5, 5, 250, 2, 0.0010
ROOT = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")

book = book_from_db(a.db if "a" in globals() else None)


def cost(y: int) -> float:
    try:
        sch = book.for_date(date(y, 6, 30), "DELIVERY")
    except Exception:
        sch = book.for_date(date(2026, 6, 30), "DELIVERY")
    p, q = Decimal(100), Decimal(1000)
    return float(
        (compute_charges(sch, "BUY", q, p).total + compute_charges(sch, "SELL", q, p).total)
        / (q * p)
    )


with psycopg.connect(a.db) as conn:
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, open::float8, high::float8, low::float8, close::float8, volume::float8"
        f" FROM {BARS} WHERE source='kite' AND ts >= '2018-06-01' AND (ts AT TIME ZONE 'Asia/Kolkata')::date < %s ORDER BY instrument_id, ts, dataset_version DESC",
        (END,),
    ).fetchall()
    acts = conn.execute(
        "SELECT instrument_id, ex_date, kind, amount::float8 FROM corporate_action WHERE ex_date >= '2018-01-01' AND ex_date < %s",
        (END,),
    ).fetchall()
d = pd.DataFrame(rows, columns=["iid", "d", "o", "h", "l", "c", "v"])
d["d"] = pd.to_datetime(d["d"])
O, H, L, C, V = (  # noqa: E741
    d.pivot(index="d", columns="iid", values=k).sort_index() for k in ("o", "h", "l", "c", "v")
)  # noqa: E741
idx, cols = C.index.values, list(C.columns)
T, S = C.shape
o, h, low, c = (x.to_numpy(dtype=float) for x in (O, H, L, C))
_, bad = ns.corporate_action_masks(idx, cols, acts)
liquid = ((C * V).rolling(20, min_periods=15).mean() / 1e7).to_numpy() >= 5.0
liquid &= ~bad & np.isfinite(c)
print(
    f"panel {T} sessions x {S} stocks; costs (round trip) "
    + ", ".join(f"{y} {100 * cost(y):.3f}%" for y in (2020, 2024))
)

# market return over the same window, per entry day i: mean over liquid stocks of close[i+HOLD]/open[i+1]-1
i_all = np.arange(T - HOLD - 1)
ret = np.full((T, S), np.nan)
ret[i_all] = c[i_all + HOLD] / o[i_all + 1] - 1
ok = liquid & np.isfinite(ret)
mkt = np.where(
    ok.sum(1) > 0, np.nansum(np.where(ok, ret, 0.0), 1) / np.maximum(ok.sum(1), 1), np.nan
)

dates = [i for i in range(T - HOLD - 1) if idx[i] >= np.datetime64(FIRST)][::STEP]
recs: list[tuple[int, int, str, bool, float]] = []  # (date index, stock, zone, uptrend, excess)
for j in range(S):
    fin = np.nonzero(np.isfinite(c[:, j]) & np.isfinite(h[:, j]) & np.isfinite(low[:, j]))[0]
    if len(fin) < lv.MIN_BARS:
        continue
    hh, ll, cc = h[fin, j], low[fin, j], c[fin, j]
    piv = lv.swing_points(hh, ll)  # a pivot at p is known only from bar p+PIVOT_K; filtered below
    sma200 = pd.Series(cc).rolling(200, min_periods=150).mean().to_numpy()
    for i in dates:
        if not (liquid[i, j] and np.isfinite(ret[i, j])):
            continue
        n = (
            int(np.searchsorted(fin, i, side="right")) - 1
        )  # position of day i inside the compressed series
        if n < lv.MIN_BARS or fin[n] != i:
            continue
        pts = [p for p in piv if n - LOOK < p[0] <= n - lv.PIVOT_K]
        sup, res = lv.nearest(lv.clusters(pts, n, cc[n]), cc[n])
        zone = "inside"
        if (
            sup
            and sup[0].touches >= MINTOUCH
            and sup[0].price * (1 - lv.BREAK_MARGIN) <= cc[n] <= sup[0].price * (1 + lv.NEAR)
        ):
            zone = "buy"
        elif (
            res
            and res[0].touches >= MINTOUCH
            and res[0].price * (1 - lv.NEAR) <= cc[n] <= res[0].price * (1 + lv.BREAK_MARGIN)
        ):
            zone = "sell"
        up = bool(np.isfinite(sma200[n]) and cc[n] > sma200[n])
        recs.append((i, j, zone, up, float(ret[i, j] - mkt[i])))

df = pd.DataFrame(recs, columns=["i", "j", "zone", "up", "ex"])
df["year"] = pd.to_datetime(idx[df["i"].to_numpy()]).year
df["cost"] = df["year"].map(lambda y: cost(int(y)) + 2 * SLIP)
df["net"] = df["ex"] - df["cost"]
z = NormalDist().inv_cdf(0.975)


def summary(x: pd.DataFrame, col: str) -> tuple[float, float, float, int, int]:
    per = x.groupby("i")[
        col
    ].mean()  # one number per signal date: signals on the same day share the market's mood
    m, se = per.mean(), per.std(ddof=1) / np.sqrt(len(per))
    return m, m - z * se, m + z * se, len(x), len(per)


def show(name: str, x: pd.DataFrame) -> None:
    if len(x) < 30:
        print(f"{name:34s} n={len(x)} (too few)")
        return
    g, n_ = summary(x, "ex"), summary(x, "net")
    print(
        f"{name:34s} n={g[3]:6d} dates={g[4]:4d}  gross excess {100 * g[0]:+.3f}% [{100 * g[1]:+.3f},{100 * g[2]:+.3f}]   net {100 * n_[0]:+.3f}% [{100 * n_[1]:+.3f},{100 * n_[2]:+.3f}]  hit>mkt {100 * (x['ex'] > 0).mean():.1f}%"
    )


for zn in ("buy", "sell", "inside"):
    x = df[df.zone == zn]
    show(f"{zn} zone, all", x)
    show(f"{zn} zone, uptrend only (secondary)", x[x.up])
    col = "net" if zn == "buy" else "ex"
    print(
        f"  by year ({col}): "
        + "  ".join(
            f"{y}: {100 * g.groupby('i')[col].mean().mean():+.2f}% (n{len(g)})"
            for y, g in x.groupby("year")
            if y >= 2020
        )
    )


def verdict(zn: str) -> str:
    x = df[df.zone == zn]
    if len(x) < 300:
        return "INCONCLUSIVE (fewer than 300 signals)"
    col, sign = ("net", 1) if zn == "buy" else ("ex", -1)
    m, lo_, hi_, _, _ = summary(x, col)
    yrs = [
        g.groupby("i")[col].mean().mean() * sign > 0
        for y, g in x.groupby("year")
        if 2020 <= y <= 2024
    ]
    ci_ok = lo_ > 0 if zn == "buy" else hi_ < 0
    return "SUCCESS" if (m * sign > 0 and ci_ok and sum(yrs) >= 4) else "FAIL"


print(f"\nVERDICT buy zone (net of costs beats the market): {verdict('buy')}")
print(f"VERDICT sell zone (lags the market, gross): {verdict('sell')}")
