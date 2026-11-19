# ruff: noqa: E501
"""Trend-pullback buy-zone study (2026-11-19). RESEARCH ONLY. FROZEN BEFORE THE FIRST RUN; nothing below was tuned.

Owner recipe: in a rising-200-day-trend stock, buy a pullback into the 20/50-day EMA band; trail a stop; leave when the 50-day EMA breaks.
  REGIME     close > SMA200 AND SMA200 > its value 20 sessions earlier (always required).
  BUY zone   EMA50 <= close <= EMA20 AND EMA20 > EMA50 AND close is 5%..10% below its 60-session high close AND RSI14 < 50 (momentum cooled).
  Entry      OPEN of T+1. One trade per stock at a time.
  Exit       first close that is either (a) below 0.97 x EMA50 (decisive break), or (b) below the highest close since entry minus 3 x ATR14 (trail), or (c) the 60th session after entry. Sold AT THAT CLOSE (slightly generous; 10 bps slippage per side is charged).
  Universe   liquid (20-day mean turnover >= Rs 5 crore), EQ, outside the +-25/+22 session window of a price-changing corporate action.
  Variants   A regime only | F + fundamentals (PIT: last 4 quarters PAT sum > 0 and latest quarter PAT > same quarter a year earlier) | G + S&P 500 above its 200-day SMA and VIX below its 252-day 90th pct (last US close before T) | FG both.
  Excess     trade return minus the equal-weight liquid-stock market return over the same entry open -> exit close window. Costs: repo DELIVERY round trip + 10 bps slippage per side.
SUCCESS RULE (fixed now), per variant: net excess per signal date (mean of per-date means) > 0 with the 95% CI over dates above 0 AND positive in at least 4 of the 5 years 2020-2024. Fewer than 300 trades = INCONCLUSIVE. Else FAIL.
Data: bars strictly before 2025-01-01 (protected holdout not read). Dividends not added back (same for trade and market).
usage: study_pullback.py [--db URL]"""

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

from algo.backtest.costs.calculator import compute_charges
from algo.backtest.costs.schedule import ScheduleBook, load_schedules
from algo.research import next_session_features as ns

END, FIRST, MAXHOLD, SLIP = "2025-01-01", "2019-11-01", 60, 0.0010
ROOT = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
book = ScheduleBook(load_schedules(ROOT / "config/cost_schedules"), allowed_statuses=("verified", "extracted_unverified", "assumed_backfill"))


def cost(y: int) -> float:
    try:
        sch = book.for_date(date(y, 6, 30), "DELIVERY")
    except Exception:
        sch = book.for_date(date(2026, 6, 30), "DELIVERY")
    p, q = Decimal(100), Decimal(1000)
    return float((compute_charges(sch, "BUY", q, p).total + compute_charges(sch, "SELL", q, p).total) / (q * p))


with psycopg.connect(a.db) as conn:
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, open::float8, high::float8, low::float8, close::float8, volume::float8"
        " FROM bar_1d WHERE source='nse' AND series='EQ' AND ts >= '2018-06-01' AND (ts AT TIME ZONE 'Asia/Kolkata')::date < %s ORDER BY instrument_id, ts, dataset_version DESC",
        (END,),
    ).fetchall()
    acts = conn.execute("SELECT instrument_id, ex_date, kind, amount::float8 FROM corporate_action WHERE ex_date >= '2018-01-01' AND ex_date < %s", (END,)).fetchall()
    glob = conn.execute("SELECT symbol, day, close::float8 FROM global_daily WHERE symbol IN ('SP500','VIXUS') AND day < %s ORDER BY day", (END,)).fetchall()
    fil = conn.execute(
        "SELECT f.instrument_id, f.period_end, f.basis, min(f.filed_at AT TIME ZONE 'Asia/Kolkata')::date, max(x.value)::float8"
        " FROM fundamental_filing f JOIN fundamental_fact x USING (filing_id) WHERE x.metric='pat' AND x.scope='QUARTER' AND f.instrument_id IS NOT NULL"
        " GROUP BY 1,2,3"
    ).fetchall()
d = pd.DataFrame(rows, columns=["iid", "d", "o", "h", "l", "c", "v"])
d["d"] = pd.to_datetime(d["d"])
O, H, L, C, V = (d.pivot(index="d", columns="iid", values=k).sort_index() for k in ("o", "h", "l", "c", "v"))
idx, cols = C.index.values, list(C.columns)
T, S = C.shape
o, h, low, c = (x.to_numpy(dtype=float) for x in (O, H, L, C))
_, bad = ns.corporate_action_masks(idx, cols, acts)
liquid = ((C * V).rolling(20, min_periods=15).mean() / 1e7).to_numpy() >= 5.0
liquid &= ~bad & np.isfinite(c)
print(f"panel {T} sessions x {S} stocks; costs (round trip) " + ", ".join(f"{y} {100 * cost(y):.3f}%" for y in (2020, 2024)))

moc = np.where(liquid, c / o - 1, np.nan)
mcc = np.full((T, S), np.nan)
mcc[1:] = c[1:] / c[:-1] - 1
mcc = np.where(liquid & np.isfinite(mcc), mcc, np.nan)
with np.errstate(all="ignore"):
    m_oc = np.nan_to_num(np.nanmean(moc, axis=1))
    m_cc = np.nan_to_num(np.nanmean(mcc, axis=1))
cum = np.cumsum(np.log1p(m_cc))


def mkt(entry: int, exit_: int) -> float:  # open[entry] -> close[exit_]
    return float(np.expm1(np.log1p(m_oc[entry]) + cum[exit_] - cum[entry]))


g = pd.DataFrame(glob, columns=["sym", "day", "c"])
g["day"] = pd.to_datetime(g["day"])
sp = g[g.sym == "SP500"].set_index("day")["c"]
vx = g[g.sym == "VIXUS"].set_index("day")["c"]
sp_ok = (sp > sp.rolling(200).mean()).astype(float).where(sp.rolling(200).mean().notna())
vx_ok = (vx < vx.rolling(252).quantile(0.9)).astype(float).where(vx.rolling(252).quantile(0.9).notna())
gl = pd.concat([sp_ok.rename("sp"), vx_ok.rename("vx")], axis=1).dropna()
gl_ok = ((gl.sp == 1) & (gl.vx == 1)).astype(float)
gpos = np.searchsorted(gl_ok.index.values, idx, side="left") - 1
glob_ok = np.where(gpos >= 0, gl_ok.to_numpy()[np.clip(gpos, 0, None)], 0.0) > 0

fq: dict[int, dict] = {}
for iid, pe, basis, filed, pat in fil:
    q = fq.setdefault(iid, {})
    cur = q.get(pe)
    if cur is None or (basis == "CONSOLIDATED" and cur[2] != "CONSOLIDATED"):
        q[pe] = (pat, filed, basis)
fund_sorted = {iid: sorted((pe, v[0], pd.Timestamp(v[1])) for pe, v in q.items()) for iid, q in fq.items()}


def fund_ok(iid: int, t: np.datetime64) -> bool:
    qs = [x for x in fund_sorted.get(iid, []) if x[2] < pd.Timestamp(t)]
    if len(qs) < 5 or sum(x[1] for x in qs[-4:]) <= 0:
        return False
    pe, pat, _ = qs[-1]
    prior = [x for x in qs if abs((pd.Timestamp(pe) - pd.Timestamp(x[0])).days - 365) <= 10]
    return bool(prior) and pat > prior[-1][1]


trades: list[tuple] = []
for j in range(S):
    fin = np.nonzero(np.isfinite(c[:, j]) & np.isfinite(h[:, j]) & np.isfinite(low[:, j]) & np.isfinite(o[:, j]))[0]
    if len(fin) < 260:
        continue
    cc, hh, ll = c[fin, j], h[fin, j], low[fin, j]
    s = pd.Series(cc)
    ema20, ema50 = s.ewm(span=20, adjust=False).mean().to_numpy(), s.ewm(span=50, adjust=False).mean().to_numpy()
    pc = np.r_[np.nan, cc[:-1]]
    atr = pd.Series(np.maximum.reduce([hh - ll, np.abs(hh - pc), np.abs(ll - pc)])).rolling(14).mean().to_numpy()
    sma = s.rolling(200, min_periods=150).mean().to_numpy()
    hi60 = s.rolling(60).max().to_numpy()
    dl = s.diff()
    rs = dl.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean() / (-dl.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = (100 - 100 / (1 + rs)).to_numpy()
    busy_until = -1
    for n in range(210, len(fin) - 2):
        i = fin[n]
        if i < busy_until or idx[i] < np.datetime64(FIRST) or not liquid[i, j]:
            continue
        if not (cc[n] > sma[n] and sma[n] > sma[n - 20]):
            continue
        dd = 1 - cc[n] / hi60[n]
        if not (ema50[n] <= cc[n] <= ema20[n] and ema20[n] > ema50[n] and 0.05 <= dd <= 0.10 and rsi[n] < 50):
            continue
        e = n + 1
        if fin[e] - i > 3 or e + MAXHOLD > len(fin) - 1:
            continue
        entry_open, top, x = o[fin[e], j], cc[e], e + MAXHOLD
        for k in range(e, e + MAXHOLD + 1):
            top = max(top, cc[k])
            if cc[k] < 0.97 * ema50[k] or cc[k] < top - 3 * atr[k]:
                x = k
                break
        ret, mk = cc[x] / entry_open - 1, mkt(fin[e], fin[x])
        F = fund_ok(cols[j], idx[i])
        trades.append((i, j, ret, ret - mk, int(pd.Timestamp(idx[i]).year), F, bool(glob_ok[i]), x - e))
        busy_until = fin[x]

df = pd.DataFrame(trades, columns=["i", "j", "ret", "ex", "year", "F", "G", "hold"])
df["mk"] = df["ret"] - df["ex"]
print(f"diagnostic: mean trade {100 * df.ret.mean():+.2f}%, mean same-window market {100 * df.mk.mean():+.2f}%, mean hold {df.hold.mean():.1f} sessions")
df["net"] = df["ex"] - (df["year"].map(lambda y: cost(int(y))) + 2 * SLIP)
z = NormalDist().inv_cdf(0.975)


def summary(x: pd.DataFrame, col: str) -> tuple[float, float, float]:
    per = x.groupby("i")[col].mean()
    m, se = per.mean(), per.std(ddof=1) / np.sqrt(len(per))
    return m, m - z * se, m + z * se


def show(name: str, x: pd.DataFrame) -> str:
    if len(x) < 30:
        print(f"{name:20s} n={len(x)} (too few)")
        return "INCONCLUSIVE"
    gm, nm = summary(x, "ex"), summary(x, "net")
    yrs = [g_.groupby("i")["net"].mean().mean() > 0 for y, g_ in x.groupby("year") if 2020 <= y <= 2024]
    v = "INCONCLUSIVE" if len(x) < 300 else ("SUCCESS" if nm[0] > 0 and nm[1] > 0 and sum(yrs) >= 4 else "FAIL")
    print(f"{name:20s} n={len(x):5d} dates={x['i'].nunique():4d} avg ret {100 * x['ret'].mean():+.2f}%  gross ex {100 * gm[0]:+.3f}% [{100 * gm[1]:+.3f},{100 * gm[2]:+.3f}]  net {100 * nm[0]:+.3f}% [{100 * nm[1]:+.3f},{100 * nm[2]:+.3f}]  win {100 * (x['ret'] > 0).mean():.0f}%  yrs>0 {sum(yrs)}/{len(yrs)}  -> {v}")
    print("    by year (net): " + "  ".join(f"{y}: {100 * g_.groupby('i')['net'].mean().mean():+.2f}% (n{len(g_)})" for y, g_ in x.groupby("year") if y >= 2020))
    return v


print()
res = {nm: show(nm, x) for nm, x in (("A regime only", df), ("F fundamentals", df[df.F]), ("G global", df[df.G]), ("FG both", df[df.F & df.G]))}
print("\nVERDICTS (frozen rule): " + "; ".join(f"{k}: {v}" for k, v in res.items()))
