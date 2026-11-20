# ruff: noqa: E501
"""Phase A of the early-large-upside research (V2 spec): validate the labels on real data and show how the V1 label differs from what could be traded.

Reads Kite adjusted bars only up to the end of the development period (config/research_holdout.json), so no holdout price is read, not even for a label window
(the last 10 development sessions simply have no full window and are dropped). Universe as V1: 20-day average traded value >= Rs 5 crore.
Parts: 1 universe and Target A base rate by year (V1 reproduction); 2 Target A vs executable Target B (next open to the horizon close); 3 Target C first-passage +10% / -5% outcomes
and the expectancy of that trade after the repo's real cost; 4 the same by how far the stock had already moved (EARLY / DEVELOPING / ALREADY_MOVING, prior 5 sessions).
usage: study_winner_labels.py [--db URL] [--min-turnover-cr 5]"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from study_common import BARS, flat_cost

from algo.research import winner_labels as wl

ROOT = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--min-turnover-cr", type=float, default=5.0)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
DEV_END = json.loads((ROOT / "config/research_holdout.json").read_text())["development_end"]

with psycopg.connect(a.db) as conn:
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, open::float8, high::float8, low::float8, close::float8, volume::float8"
        f" FROM {BARS} WHERE source='kite' AND ts >= '2019-09-01' AND (ts AT TIME ZONE 'Asia/Kolkata')::date <= %s ORDER BY instrument_id, ts, dataset_version DESC",
        (DEV_END,),
    ).fetchall()
d = pd.DataFrame(rows, columns=["iid", "d", "o", "h", "l", "c", "v"])
del rows
d["d"] = pd.to_datetime(d["d"])
pv = {k: d.pivot(index="d", columns="iid", values=k).sort_index() for k in "ohlcv"}
del d
OP, H, L, C, V = (pv[k].to_numpy() for k in "ohlcv")
idx = pv["c"].index
T, S = C.shape
yr = np.broadcast_to(idx.year.to_numpy()[:, None], (T, S))
liq = ((pv["c"] * pv["v"]).rolling(20, min_periods=15).mean() / 1e7 >= a.min_turnover_cr).to_numpy()
print(
    f"bars {idx[0].date()} to {idx[-1].date()} (development period only; holdout not read), {S} stocks, {T} sessions"
)

# labels, in column chunks to keep memory small
names = (
    "valid",
    "target_a",
    "ret_exec",
    "target_b_5",
    "target_b_8",
    "target_b_10",
    "outcome",
    "exit_return",
    "exit_session",
    "mfe",
    "mae",
)
R = {
    n: np.zeros((T, S), dtype=bool if n.startswith(("valid", "target")) else "float64")
    for n in names
}
for s0 in range(0, S, 400):
    sl = slice(s0, s0 + 400)
    r = wl.winner_labels(OP[:, sl], H[:, sl], L[:, sl], C[:, sl])
    for n in names:
        R[n][:, sl] = getattr(r, n)
gap1 = np.full((T, S), np.nan)
gap1[:-1] = OP[1:] / C[:-1] - 1  # the overnight gap between the signal close and the entry open
prior5 = np.full((T, S), np.nan)
prior5[5:] = C[5:] / C[:-5] - 1
m = liq & R["valid"] & np.isfinite(prior5)
COST = flat_cost()

print(
    f"\n=== 1. universe and the V1 label (Target A: close 10 sessions later >= 10% above today's close). {int(m.sum()):,} liquid stock-days with a full window"
)
print(
    "year    rows   Target A rate   (V1 log: 2019 10.24  2020 15.92  2021 13.32  2022  9.43  2023 11.52  2024 11.99)"
)
for y in sorted(set(idx.year)):
    sel = m & (yr == y)
    if sel.any():
        print(f"{y}  {int(sel.sum()):>7,}   {100 * R['target_a'][sel].mean():>6.2f}%")

print(
    "\n=== 2. Target A (assumes the close of the signal day) against Target B (what the next open could have bought): the share that is still there after the open"
)
print(
    "year   A rate   B>=5%   B>=8%   B>=10%   A winners still >=10% from the open   median gap of A winners   A winners already gapped +3% or more"
)
for y in sorted(set(idx.year)):
    sel = m & (yr == y)
    w = sel & R["target_a"]
    if not sel.any():
        continue
    print(
        f"{y}  {100 * R['target_a'][sel].mean():>6.2f}% {100 * R['target_b_5'][sel].mean():>6.2f}% {100 * R['target_b_8'][sel].mean():>6.2f}% {100 * R['target_b_10'][sel].mean():>7.2f}%"
        f"   {100 * R['target_b_10'][w].mean():>34.1f}%   {100 * np.nanmedian(gap1[w]):>+22.2f}%   {100 * (gap1[w] >= 0.03).mean():>34.1f}%"
    )
w_all = m & R["target_a"]
print(
    f"all   of {int(w_all.sum()):,} Target A winners: {100 * R['target_b_10'][w_all].mean():.1f}% are still +10% from the next open; {100 * R['target_b_5'][w_all].mean():.1f}% still +5%"
)

OUT = {
    wl.SUCCESS: "SUCCESS",
    wl.FAILURE: "FAILURE",
    wl.NO_EVENT: "NO_EVENT",
    wl.AMBIGUOUS: "AMBIGUOUS",
}
print(
    f"\n=== 3. Target C: +10% target / -5% stop from the next open, 10 sessions, daily bars (an ambiguous candle is never ordered). Real round-trip cost {100 * COST:.2f}%"
)
print(
    "year   SUCCESS  FAILURE  NO_EVENT AMBIGUOUS | mean exit return gross  net   | success:failure   (ambiguous excluded from the expectancy)"
)
for y in [*sorted(set(idx.year)), "all"]:
    sel = m & (yr == y) if y != "all" else m
    if not sel.any():
        continue
    o_ = R["outcome"][sel]
    share = {k: 100 * (o_ == k).mean() for k in OUT}
    er = R["exit_return"][sel]
    ok = np.isfinite(er)
    print(
        f"{y!s:<5} {share[wl.SUCCESS]:>7.2f}% {share[wl.FAILURE]:>7.2f}% {share[wl.NO_EVENT]:>8.2f}% {share[wl.AMBIGUOUS]:>8.2f}% | {100 * er[ok].mean():>+14.2f}%  {100 * (er[ok].mean() - COST):>+6.2f}% | {share[wl.SUCCESS] / max(share[wl.FAILURE], 1e-9):>10.2f}"
    )

print(
    "\n=== 4. by how far the stock had already moved (prior 5 sessions): research segments, not trading rules"
)
seg = {
    "EARLY (<3%)": prior5 < 0.03,
    "DEVELOPING (3-5%)": (prior5 >= 0.03) & (prior5 <= 0.05),
    "ALREADY_MOVING (>5%)": prior5 > 0.05,
}
print(
    f"{'segment':<22}{'rows':>10}{'share':>8}{'A rate':>8}{'B>=10%':>8}{'C success':>10}{'C failure':>10}{'exit ret gross':>16}{'net':>8}"
)
for nm, sg in seg.items():
    sel = m & sg
    er = R["exit_return"][sel]
    ok = np.isfinite(er)
    print(
        f"{nm:<22}{int(sel.sum()):>10,}{100 * sel.sum() / m.sum():>7.1f}%{100 * R['target_a'][sel].mean():>7.2f}%{100 * R['target_b_10'][sel].mean():>7.2f}%"
        f"{100 * (R['outcome'][sel] == wl.SUCCESS).mean():>9.2f}%{100 * (R['outcome'][sel] == wl.FAILURE).mean():>9.2f}%{100 * er[ok].mean():>+15.2f}%{100 * (er[ok].mean() - COST):>+7.2f}%"
    )
