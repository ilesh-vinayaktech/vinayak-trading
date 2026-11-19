# ruff: noqa: E501
"""Study: which inside-bar breakouts and breakdowns are followed through?

The chart marks an inside-bar break (frontend/lib/autoAnalysis.ts `insideBreak`): a bar wholly inside the bar before it (the mother) and at most 60%
of its range, a mother at least as big as the recent average bar, and the first close beyond the mother's high (breakout) or low (breakdown).
This replays that rule over every liquid NSE stock since late 2019 and measures what happened next, split by the conditions traders talk about:
mother size, how tight the inside bar is, how many inside bars, volume on the break, how decisively the break bar closed, the trend before it,
and whether it cleared a fresh 20-day high or low.

Everything is known at the close of the break bar; the return runs from that close. Return = close(+H sessions) / close - 1, less the median stock that
day, then signed by the direction of the break (a breakdown that keeps falling counts as a win). A window that crosses a split or bonus is dropped.
usage: study_inside_bar.py [--db URL] [--horizon 10] [--min-turnover-cr 5]"""

import argparse
import os
import sys

import numpy as np
import pandas as pd
import psycopg

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--horizon", type=int, default=10)
ap.add_argument("--min-turnover-cr", type=float, default=5.0)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
H_ = a.horizon

with psycopg.connect(a.db) as conn:
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, open::float8, high::float8, low::float8, close::float8, volume::float8"
        " FROM bar_1d WHERE source='nse' AND series='EQ' AND ts >= '2019-09-01' ORDER BY instrument_id, ts, dataset_version DESC"
    ).fetchall()
    splits = conn.execute(
        "SELECT instrument_id, ex_date FROM corporate_action WHERE kind IN ('split','bonus') AND status='ok'"
    ).fetchall()

df = pd.DataFrame(rows, columns=["iid", "d", "o", "h", "l", "c", "v"])
del rows


def mat(frame: pd.DataFrame, col: str) -> pd.DataFrame:
    return frame.pivot(index="d", columns="iid", values=col).sort_index()


Hh, L, C, V = (mat(df, k) for k in ("h", "l", "c", "v"))
del df
R = Hh - L
avg14 = R.shift(1).rolling(14, min_periods=14).mean()
turnover = (C * V).rolling(20, min_periods=15).mean() / 1e7
vol_ratio = V / V.shift(1).rolling(20, min_periods=15).mean()
sma50 = C.rolling(50, min_periods=50).mean()
hi20 = Hh.shift(1).rolling(20, min_periods=20).max()
lo20 = L.shift(1).rolling(20, min_periods=20).min()

# inside bars, runs of them, and the biggest inside-bar range in the run
ins = (Hh < Hh.shift(1)) & (L > L.shift(1))
iv, rr = ins.to_numpy(), R.fillna(0).to_numpy()
rv, mv = np.zeros(iv.shape, dtype=int), np.zeros(iv.shape)
for t in range(1, len(C.index)):
    rv[t] = np.where(iv[t], rv[t - 1] + 1, 0)
    mv[t] = np.where(iv[t], np.maximum(mv[t - 1], rr[t]), 0.0)
run = pd.DataFrame(rv, index=C.index, columns=C.columns)
runmax = pd.DataFrame(mv, index=C.index, columns=C.columns)

K = 6
mother_h = pd.DataFrame(np.nan, index=C.index, columns=C.columns)
mother_l = mother_h.copy()
for k in range(
    1, K + 1
):  # a run of k inside bars ended on the previous bar: the mother is k+1 bars back
    sel = run.shift(1) == k
    mother_h = mother_h.where(~sel, Hh.shift(k + 1))
    mother_l = mother_l.where(~sel, L.shift(k + 1))
mother_r = mother_h - mother_l
k_run = run.shift(1)
tight = runmax.shift(1) / mother_r
valid = (k_run >= 1) & (k_run <= K) & (mother_r >= avg14) & (tight <= 0.6)
up = valid & (C > mother_h)
down = valid & (C < mother_l)

fwd = C.shift(-H_) / C - 1
bad = pd.DataFrame(False, index=C.index, columns=C.columns)
idx = C.index.values
for iid, ex_date in splits:
    if iid in bad.columns:
        i = int(np.searchsorted(idx, np.datetime64(ex_date)))
        bad.iloc[max(0, i - 25) : min(len(idx), i + H_ + 1), bad.columns.get_loc(iid)] = True
liquid = (turnover >= a.min_turnover_cr) & ~bad & fwd.notna()
ex = fwd.sub(fwd.where(liquid).median(axis=1), axis=0)

# features at the break bar
atr_mult = mother_r / avg14
close_loc_up = (C - L) / R
close_loc_down = (Hh - C) / R
trend_up = (C.shift(1) > sma50) & (sma50 > sma50.shift(10))
trend_down = (C.shift(1) < sma50) & (sma50 < sma50.shift(10))


def collect(direction: str) -> pd.DataFrame:
    m = (up if direction == "up" else down) & liquid
    sign = 1 if direction == "up" else -1
    cols = {
        "ex": ex * sign,
        "mother_atr": atr_mult,
        "tight": tight,
        "k": k_run,
        "vr": vol_ratio,
        "loc": close_loc_up if direction == "up" else close_loc_down,
        "with_trend": (trend_up if direction == "up" else trend_down).astype(float),
        "against_trend": (trend_down if direction == "up" else trend_up).astype(float),
        "fresh_extreme": ((C > hi20) if direction == "up" else (C < lo20)).astype(float),
        "clear": ((C - mother_h) if direction == "up" else (mother_l - C)) / avg14,
    }
    out = pd.concat({k: v.where(m).stack() for k, v in cols.items()}, axis=1).reset_index()
    out.columns = ["d", "iid", *out.columns[2:]]
    return out.dropna(subset=["ex", "k"]).reset_index(
        drop=True
    )  # stack() keeps the days with no signal as NaN rows


base = ex.where(liquid).stack().dropna()
print(
    f"horizon {H_} sessions, turnover >= {a.min_turnover_cr} Cr, {len(base):,} stock-days; a random stock-day: beats the market {100 * (base > 0).mean():.1f}%, trails it {100 * (base < 0).mean():.1f}% (mean {100 * base.mean():+.2f}%, median {100 * base.median():+.2f}%). Compare a breakout with the first, a breakdown with the second; a breakout's mean with {100 * base.mean():+.2f}%, a breakdown's with {-100 * base.mean():+.2f}%.\n"
)


def table(title: str, t: pd.DataFrame, key, labels: dict) -> None:
    key = pd.Series(np.asarray(key, dtype=object), index=t.index)
    print(f"--- {title}")
    print(f"{'':<34}{'breaks':>8}{'moved on %':>12}{'median %':>10}{'mean %':>9}{'t (by day)':>12}")
    for lab, name in labels.items():
        g = t[key == lab]
        if len(g) < 30:
            print(f"{name:<34}{len(g):>8}")
            continue
        pw = g.groupby("d")["ex"].mean()
        tt = (
            pw.mean() / (pw.std() / np.sqrt(len(pw)))
            if len(pw) > 5 and pw.std() > 0
            else float("nan")
        )
        print(
            f"{name:<34}{len(g):>8,}{100 * (g['ex'] > 0).mean():>12.1f}{100 * g['ex'].median():>10.2f}{100 * g['ex'].mean():>9.2f}{tt:>12.2f}"
        )
    print()


def cut(s: pd.Series, edges: list[float], labels: list[str]) -> np.ndarray:
    return np.asarray(pd.cut(s, edges, labels=labels, right=False).astype(object))


for direction in ("up", "down"):
    t = collect(direction)
    word = "BREAKOUT (up)" if direction == "up" else "BREAKDOWN (down)"
    print(
        f"================ {word}: {len(t):,} signals; signed so that + means it kept going the way of the break\n"
    )
    table("all breaks", t, ["all"] * len(t), {"all": "every break"})
    table(
        "mother bar size vs the average bar",
        t,
        cut(t["mother_atr"], [0, 1.5, 2.5, 99], ["a", "b", "c"]),
        {"a": "1 to 1.5x", "b": "1.5 to 2.5x", "c": "over 2.5x"},
    )
    table(
        "inside bar size vs its mother",
        t,
        cut(t["tight"], [0, 0.3, 0.45, 0.61], ["a", "b", "c"]),
        {"a": "under 30%", "b": "30 to 45%", "c": "45 to 60%"},
    )
    table(
        "how many inside bars",
        t,
        np.where(t["k"] >= 2, "2+", "1"),
        {"1": "one inside bar", "2+": "two or more"},
    )
    table(
        "volume on the break bar vs its 20-day average",
        t,
        cut(t["vr"], [0, 1.0, 1.5, 99], ["a", "b", "c"]),
        {"a": "below average", "b": "1 to 1.5x", "c": "over 1.5x"},
    )
    table(
        "where the break bar closed in its range (1 = at the extreme)",
        t,
        cut(t["loc"], [-1, 0.5, 0.8, 1.01], ["a", "b", "c"]),
        {"a": "weak close (<0.5)", "b": "middling (0.5-0.8)", "c": "strong close (>0.8)"},
    )
    table(
        "trend before the break (50-day average)",
        t,
        np.where(
            t["with_trend"] == 1, "with", np.where(t["against_trend"] == 1, "against", "none")
        ),
        {"with": "with the trend", "none": "no clear trend", "against": "against the trend"},
    )
    table(
        "a fresh 20-day high / low",
        t,
        np.where(t["fresh_extreme"] == 1, "yes", "no"),
        {"yes": "breaks the 20-day extreme", "no": "inside the 20-day range"},
    )
    table(
        "how far past the mother bar it closed (x average bar)",
        t,
        cut(t["clear"], [-9, 0.1, 0.3, 99], ["a", "b", "c"]),
        {"a": "barely past (<0.1)", "b": "a little past", "c": "clearly past (>0.3)"},
    )
    good = (t["vr"] >= 1.5) & (t["loc"] >= 0.8) & (t["with_trend"] == 1) & (t["fresh_extreme"] == 1)
    table(
        "stacked: volume 1.5x+, strong close, with the trend, fresh 20-day extreme",
        t,
        np.where(good, "yes", "no"),
        {"yes": "all four", "no": "not all four"},
    )
    t.to_pickle(f"/tmp/ib_{direction}_{H_}.pkl")
