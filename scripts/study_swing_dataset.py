# ruff: noqa: E501
"""Swing research, Phase 1: the new ATR triple-barrier dataset and a first one-feature-at-a-time strategy test (development period only; the holdout is never read).

Entry at the next open after the signal close; barriers 1.5 ATR up / 1.0 ATR down, 10 sessions (src/algo/research/swing_labels.py); features from src/algo/research/swing_features.py.
Universe: 20-day average traded value >= Rs 5 crore. Cost: the repo's real round trip (study_common.flat_cost) charged on every trade.
Parts: 1 label mix and the UNSELECTED trade by year; 2 each feature, top and bottom decile of the day's liquid stocks: net return, edge over the same-day average, positive years, month-block 95% interval.
With 29 features x 2 sides, the best of the list is partly luck: read an edge only when its interval excludes 0 AND most years agree. usage: study_swing_dataset.py [--db URL] [--up 1.5] [--dn 1.0] [--horizon 10]"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from study_common import BARS, flat_cost

from algo.research import swing_features as sf
from algo.research import swing_labels as sl

ROOT = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--up", type=float, default=1.5)
ap.add_argument("--dn", type=float, default=1.0)
ap.add_argument("--horizon", type=int, default=10)
ap.add_argument("--min-turnover-cr", type=float, default=5.0)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
DEV_END = json.loads((ROOT / "config/research_holdout.json").read_text())["development_end"]

with psycopg.connect(a.db) as conn:
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, open::float8, high::float8, low::float8, close::float8, volume::float8, delivery_qty::float8"
        f" FROM {BARS} WHERE source='kite' AND ts >= '2019-09-01' AND (ts AT TIME ZONE 'Asia/Kolkata')::date <= %s ORDER BY instrument_id, ts, dataset_version DESC",
        (DEV_END,),
    ).fetchall()
    COST = flat_cost(a.db)
d = pd.DataFrame(rows, columns=["iid", "d", "o", "h", "l", "c", "v", "dq"])
del rows
d["d"] = pd.to_datetime(d["d"])
pv = {
    k: d.pivot(index="d", columns="iid", values=k).sort_index()
    for k in ("o", "h", "l", "c", "v", "dq")
}
del d
OP, H, L, C, V, DQ = (pv[k].to_numpy() for k in ("o", "h", "l", "c", "v", "dq"))
idx = pv["c"].index
T, S = C.shape
yr = np.broadcast_to(idx.year.to_numpy()[:, None], (T, S))
liq = ((pv["c"] * pv["v"]).rolling(20, min_periods=15).mean() / 1e7 >= a.min_turnover_cr).to_numpy()
print(
    f"bars {idx[0].date()} to {idx[-1].date()} (development period only), {S} stocks, {T} sessions; cost {100 * COST:.2f}% round trip; barriers {a.up}/{a.dn} ATR, {a.horizon} sessions"
)

lab = sl.barrier_labels(OP, H, L, C, sl.atr(H, L, C, 14), a.up, a.dn, a.horizon)
m = liq & (lab.outcome != sl.NONE) & np.isfinite(lab.ret)
net = lab.ret - COST

print(
    f"\n=== 1. labels and the unselected trade: {int(m.sum()):,} liquid stock-days with a full window"
)
print(
    "year      rows  PROFIT  LOSS  TIMEOUT  ambiguous | gross    net   | mean MFE  mean MAE | days held"
)
for y in [*sorted(set(idx.year)), "all"]:
    sel = m if y == "all" else m & (yr == y)
    if not sel.any():
        continue
    o_ = lab.outcome[sel]
    print(
        f"{y!s:<5} {int(sel.sum()):>9,} {100 * (o_ == sl.PROFIT_FIRST).mean():>6.1f}% {100 * (o_ == sl.LOSS_FIRST).mean():>5.1f}% {100 * (o_ == sl.TIMEOUT).mean():>7.1f}% {100 * lab.ambiguous[sel].mean():>8.2f}% |"
        f" {100 * lab.ret[sel].mean():>+6.2f}% {100 * net[sel].mean():>+6.2f}% | {100 * lab.mfe[sel].mean():>+7.2f}% {100 * lab.mae[sel].mean():>+8.2f}% | {lab.sessions[sel].mean():>5.1f}"
    )

# features in column chunks (memory), then decile means per day
dec_top: dict[str, np.ndarray] = {}
dec_bot: dict[str, np.ndarray] = {}
day_avg = np.where(m, net, np.nan)
avg = np.nanmean(day_avg, axis=1)
for k in sf.META:
    dec_top[k] = np.full(T, np.nan)
    dec_bot[k] = np.full(T, np.nan)
chunk = 500
feat = {k: np.full((T, S), np.nan, dtype=np.float32) for k in sf.META}
for s0 in range(0, S, chunk):
    c = slice(s0, s0 + chunk)
    f = sf.features(OP[:, c], H[:, c], L[:, c], C[:, c], V[:, c], DQ[:, c])
    for k in f:
        feat[k][:, c] = f[k]
for k in sf.META:
    x = pd.DataFrame(np.where(m, feat[k], np.nan))
    r = x.rank(axis=1, pct=True).to_numpy()
    top = np.where(r > 0.9, net, np.nan)
    bot = np.where(r <= 0.1, net, np.nan)
    with np.errstate(all="ignore"):
        cnt_t, cnt_b = np.sum(np.isfinite(top), 1), np.sum(np.isfinite(bot), 1)
        dec_top[k] = np.where(cnt_t >= 3, np.nanmean(top, 1), np.nan)
        dec_bot[k] = np.where(cnt_b >= 3, np.nanmean(bot, 1), np.nan)
del feat

months = idx.to_period("M")
mon_codes = pd.factorize(months)[0]
rng = np.random.default_rng(7)


def month_ci(series: np.ndarray) -> tuple[float, float, float]:
    ok = np.isfinite(series)
    s, mc = series[ok], mon_codes[ok]
    sums = np.bincount(mc, weights=s, minlength=mon_codes.max() + 1)
    cnts = np.bincount(mc, minlength=mon_codes.max() + 1)
    keep = cnts > 0
    sums, cnts = sums[keep], cnts[keep]
    n = len(sums)
    boots = [(sums[i].sum() / cnts[i].sum()) for i in (rng.integers(0, n, n) for _ in range(1000))]
    return s.mean(), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


print(
    "\n=== 2. one feature at a time: the day's top / bottom 10% of liquid stocks, net of cost, minus the same-day average stock"
)
print(
    "feature            group      side  net/trade  edge vs avg  [95% month-block CI]       positive years"
)
res = []
years = sorted(set(idx.year))
for k in sf.META:
    for side, ser in (("top", dec_top[k]), ("bot", dec_bot[k])):
        edge = ser - avg
        mean, lo, hi = month_ci(edge)
        pos = sum(
            np.nanmean(edge[idx.year == y]) > 0
            for y in years
            if np.isfinite(edge[idx.year == y]).any()
        )
        res.append((mean, k, side, np.nanmean(ser), lo, hi, pos))
for mean, k, side, nt, lo, hi, pos in sorted(res, reverse=True):
    flag = "  <-- CI above 0" if lo > 0 else ""
    print(
        f"{k:<18} {sf.META[k]:<10} {side}  {100 * nt:>+8.2f}%  {100 * mean:>+10.2f}%  [{100 * lo:>+6.2f}%, {100 * hi:>+6.2f}%]   {pos}/{len(years)}{flag}"
    )
