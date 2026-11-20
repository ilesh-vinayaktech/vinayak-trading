# ruff: noqa: E501
"""Does trend information improve EXIT decisions and risk (2026-11-19)? Not a strategy that must beat the market. RESEARCH ONLY. FROZEN BEFORE THE FIRST RUN; nothing below was tuned.

Design: the ENTRIES are neutral and fixed, so only the exit differs. Entry = every 10th session per stock (t + stock number divisible by 10), liquid stocks (20-day turnover >= Rs 5 crore), 2020-2024, buy the OPEN of T+1. No signal, no trend, no model.
Each trade may run at most 60 sessions. A policy is evaluated at every close from the entry day on; the first close that triggers it sells at the NEXT open; no trigger = sell at the 60-session cap. Trades touching missing bars or the end of the data are dropped.
Policies (ATR = Wilder ATR14 on that day; peak = highest close since entry, entry day included; EMA50 and the trend state are the same as trend_ride):
  HOLD60    never exits before the cap                           T20     sells after 20 sessions
  FIX3      close <= entry open - 3 x ATR(signal day)  (fixed stop, price only)
  TRAIL2/3/4  close <= peak - k x ATR(today)  (trailing stop, price only: NO trend information)
  EMA50     close < EMA50                                        DOWN    state DOWN (close < EMA50 and EMA50 fell >= 0.5% in 10 sessions)
  ADAPT     trailing stop that is 4 ATR while the state is UP and 2 ATR otherwise (the stop width uses trend information)
  TRAIL3+EMA50  TRAIL3 or EMA50 (the trend_ride exit)
Control for exposure: every policy gets a RANDOM TWIN: the same trades with their hold lengths shuffled among trades entered in the same year (10 shuffles, fixed seed). The twin has the same hold-length distribution and no information about the price path, so
"policy minus twin" is what the exit TIMING itself adds, with exposure held equal. Reported: net return (cost = the repo's real round trip, charged once), worst-5% tail (mean of the lowest 5% of net returns), average worst drawdown from entry (MAE, closes), giveback (best close return before the exit minus the exit return).
Significance: monthly means of the paired difference (entry month blocks, because trades overlap in time), t over months.
SUCCESS RULE (fixed now). A policy HAS EXIT INFORMATION if, against its twin: mean net return difference > 0 (at least 0.0001%, so an identical twin cannot pass on float noise) with t(months) > 1.96, AND a positive difference in at least 4 of the 5 years 2020-2024, AND its worst-5% tail is no worse than the twin's.
TREND ADDS beyond a price-only stop if, for that policy, (policy - twin) - (TRAIL3 - twin) > 0 with t(months) > 1.96 and positive in >= 4 of 5 years (checked for ADAPT, TRAIL3+EMA50, EMA50, DOWN).
Fewer than 5,000 trades = INCONCLUSIVE. Printed descriptive only: exit-vs-twin by the trend state at entry.
usage: study_trend_exits.py [--db URL]"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from study_common import BARS, flat_cost  # noqa: E402,I001

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
END = json.loads(
    (Path(__file__).resolve().parents[1] / "config/research_holdout.json").read_text()
)["holdout_start"]
with psycopg.connect(a.db) as conn:
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, open::float8, high::float8, low::float8, close::float8, volume::float8"
        f" FROM {BARS} WHERE source='kite' AND ts >= '2019-09-01' AND (ts AT TIME ZONE 'Asia/Kolkata')::date < %s ORDER BY instrument_id, ts, dataset_version DESC", (END,)
    ).fetchall()  # fmt: skip
d = pd.DataFrame(rows, columns=["iid", "d", "o", "h", "l", "c", "v"])
O, H, L, C, V = (  # noqa: E741
    d.pivot(index="d", columns="iid", values=k).sort_index() for k in ("o", "h", "l", "c", "v")
)
T, S = C.shape
idx = pd.DatetimeIndex(C.index)
liq = ((C * V).rolling(20, min_periods=15).mean() / 1e7) >= 5.0
ready = C.notna().cumsum() >= 80
ema50 = C.ewm(span=50, adjust=False).mean()
pc = C.shift(1)
tr_ = np.maximum(H - L, np.maximum((H - pc).abs(), (L - pc).abs()))
atr = tr_.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
UP = ((C > ema50) & (ema50 > ema50.shift(10) * 1.005)).to_numpy()
DOWN = ((C < ema50) & (ema50 < ema50.shift(10) * 0.995)).to_numpy()
o, c, at, em = (x.to_numpy(float) for x in (O, C, atr, ema50))
COST = flat_cost()
CAP = 60

# ---- neutral entries -> path matrices
ok = (liq & ready).to_numpy() & np.isfinite(at)
ts_, ss_ = np.nonzero(ok)
year = idx.year.to_numpy()
sel = (year[ts_] >= 2020) & ((ts_ + ss_) % 10 == 0) & (ts_ + CAP + 2 < T)
ts_, ss_ = ts_[sel], ss_[sel]
K = np.arange(CAP + 1)
rows_ = ts_[:, None] + 1 + K[None, :]  # entry open is day t+1
op = o[rows_, ss_[:, None]]  # opens at day e+k, k=0..CAP
cl = c[rows_[:, :CAP], ss_[:, None]]  # closes at day e+k, k=0..CAP-1
good = np.isfinite(op).all(1) & np.isfinite(cl).all(1)
ts_, ss_, op, cl, rows_ = ts_[good], ss_[good], op[good], cl[good], rows_[good]
n = len(ts_)
o0 = op[:, 0]
r_ = rows_[:, :CAP]
ATR = at[r_, ss_[:, None]]
EMA = em[r_, ss_[:, None]]
isup, isdown = UP[r_, ss_[:, None]], DOWN[r_, ss_[:, None]]
atr0 = at[ts_, ss_][:, None]
peak = np.maximum.accumulate(cl, axis=1)
cmin = np.minimum.accumulate(cl, axis=1)
yr = year[ts_ + 1]
month = (ts_ + 1) // 21
up_at_entry = UP[ts_, ss_]


def first(
    cond: np.ndarray,
) -> np.ndarray:  # first decision index k that triggers, else the cap (CAP-1)
    cond = cond.copy()
    cond[:, -1] = True
    return cond.argmax(axis=1)


def trail(m):
    return cl <= peak - m * ATR


POL = {
    "HOLD60": first(np.zeros_like(cl, bool)),
    "T20": first(np.broadcast_to(K[:CAP] == 19, cl.shape)),
    "FIX3": first(cl <= o0[:, None] - 3 * atr0),
    "TRAIL2": first(trail(2)),
    "TRAIL3": first(trail(3)),
    "TRAIL4": first(trail(4)),
    "EMA50": first(cl < EMA),
    "DOWN": first(isdown),
    "ADAPT": first(cl <= peak - np.where(isup, 4, 2) * ATR),
    "TRAIL3+EMA50": first(trail(3) | (cl < EMA)),
}


def metrics(xk: np.ndarray) -> dict[str, np.ndarray]:
    i = np.arange(n)
    gross = op[i, xk + 1] / o0 - 1
    best = np.maximum(peak[i, xk] / o0 - 1, 0)
    return {
        "ret": gross - COST,
        "mae": np.minimum(cmin[i, xk] / o0 - 1, 0),
        "give": best - gross,
        "days": (xk + 1).astype(float),
    }


def twin(xk: np.ndarray, reps: int = 10) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(20261119)
    acc: dict[str, list] = {}
    for _ in range(reps):
        sh = xk.copy()
        for y in np.unique(yr):
            m = np.flatnonzero(yr == y)
            sh[m] = xk[rng.permutation(m)]
        for k, v in metrics(sh).items():
            acc.setdefault(k, []).append(v)
    return {k: np.mean(v, axis=0) for k, v in acc.items()}


def tail5(x: np.ndarray) -> float:
    return float(np.sort(x)[: max(1, len(x) // 20)].mean())


def tmonths(diff: np.ndarray) -> float:
    g = pd.Series(diff).groupby(month).mean()
    return (
        float(g.mean() / (g.std(ddof=1) / np.sqrt(len(g))))
        if len(g) > 5 and g.std(ddof=1) > 0
        else float("nan")
    )


def years_pos(diff: np.ndarray) -> int:
    return sum(float(diff[yr == y].mean()) > 0 for y in range(2020, 2025))


h60 = metrics(POL["HOLD60"])["ret"]
print(
    f"panel {T} sessions x {S} stocks; {n:,} neutral entries 2020-2024, cap {CAP} sessions, cost {100 * COST:.2f}%"
)
print(f"HOLD60 baseline: mean net {100 * h60.mean():.2f}%, worst-5% tail {100 * tail5(h60):.1f}%")
print(
    f"\n{'policy':<14}{'days':>6}{'net %':>8}{'twin %':>8}{'diff %':>8}{'t(mo)':>7}{'yrs+':>5} {'tail5 %':>8}{'twin':>7} {'MAE %':>7}{'twin':>7} {'giveback':>9}{'twin':>7}  frozen rule"
)
store, tw_ret = {}, {}
for name, xk in POL.items():
    m, w = metrics(xk), twin(xk)
    diff = m["ret"] - w["ret"]
    store[name], tw_ret[name] = m, w["ret"]
    t5, w5 = tail5(m["ret"]), tail5(w["ret"])
    t_, yp = tmonths(diff), years_pos(diff)
    has = n >= 5000 and diff.mean() > 1e-6 and t_ > 1.96 and yp >= 4 and t5 >= w5
    print(
        f"{name:<14}{m['days'].mean():>6.1f}{100 * m['ret'].mean():>8.2f}{100 * w['ret'].mean():>8.2f}{100 * diff.mean():>8.2f}{t_:>7.1f}{yp:>4}/5 {100 * t5:>8.1f}{100 * w5:>7.1f} {100 * m['mae'].mean():>7.1f}{100 * w['mae'].mean():>7.1f} {100 * m['give'].mean():>9.1f}{100 * w['give'].mean():>7.1f}  {'HAS EXIT INFO' if has else 'no'}"
    )
print(
    "\nTREND ADDS beyond the price-only TRAIL3? (policy-twin) minus (TRAIL3-twin), per trade, net return %"
)
base = store["TRAIL3"]["ret"] - tw_ret["TRAIL3"]
for name in ("ADAPT", "TRAIL3+EMA50", "EMA50", "DOWN"):
    dd = (store[name]["ret"] - tw_ret[name]) - base
    t_, yp = tmonths(dd), years_pos(dd)
    verdict = "TREND ADDS" if n >= 5000 and dd.mean() > 0 and t_ > 1.96 and yp >= 4 else "no"
    print(
        f"  {name:<14}{100 * dd.mean():>7.2f}%  t(months) {t_:>5.1f}  years+ {yp}/5  -> {verdict}"
    )
print("\ndescriptive only: (policy - twin) net %, entries split by the trend state at entry")
for name in ("TRAIL3", "ADAPT", "EMA50", "TRAIL3+EMA50"):
    diff = store[name]["ret"] - tw_ret[name]
    print(
        f"  {name:<14} entered UP {100 * diff[up_at_entry].mean():>6.2f}% (n {int(up_at_entry.sum()):,})   not UP {100 * diff[~up_at_entry].mean():>6.2f}% (n {int((~up_at_entry).sum()):,})"
    )
