# ruff: noqa: E501
"""Study: can a stock's OWN direction (up or down against its own past) be called, separately from how it ranks against other stocks?

Two own-direction questions, each with stock-only features and with market-state features added:
  U  closes higher 5 sessions on (absolute up)
  Z  its next 5-session return beats its own recent pace (the average of its 5-session returns over the previous 60 sessions)
The relative rank (does it beat the other stocks) is the rise odds already built; here it is the comparison. Judged only on years the models never saw, by year, with the number of different
days behind every high-precision tail and its lift over the same day's base rate. An absolute call mostly says "the market goes up", so the same-day lift is the honest measure of stock selection.
usage: study_own_direction.py [--db URL]"""

import argparse
import os
import sys

import numpy as np
import pandas as pd
import psycopg
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from study_common import BARS, use_kite_panel  # noqa: E402,I001

from algo.market import rise_odds as ro

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")

use_kite_panel(ro)  # Kite adjusted bars, not the NSE raw panel + split mask
with psycopg.connect(a.db) as conn:
    last = conn.execute(
        f"SELECT max((ts AT TIME ZONE 'Asia/Kolkata')::date) FROM {BARS} WHERE source='kite'"
    ).fetchone()[0]
    p = ro.load_panel(conn, ro.HISTORY_FROM, last)
    splits = ro.load_splits(conn)
C, H, L = p.close, p.high, p.low
T, S = C.shape
idx = np.array(C.index, dtype="datetime64[D]")
feats = ro.features(p)
ret1 = C.pct_change()
feats["vol20"] = ret1.rolling(20, min_periods=10).std() * 100
feats["atr14"] = (H - L).rolling(14, min_periods=14).mean() / C * 100
feats["up_days10"] = (ret1 > 0).astype("float32").rolling(10).sum()
feats["r5_z"] = feats["r5"] / (
    feats["vol20"] / 100 * np.sqrt(5)
)  # the last 5 sessions' move in units of the stock's own usual 5-session move
r5 = C / C.shift(5) - 1
feats["pace60"] = r5.rolling(
    60, min_periods=40
).mean()  # the stock's own average 5-session return over the last 60 sessions

sma50, sma200 = C.rolling(50, min_periods=50).mean(), C.rolling(200, min_periods=200).mean()
mk = {
    "breadth50": (C > sma50).where(sma50.notna()).mean(axis=1),
    "breadth200": (C > sma200).where(sma200.notna()).mean(axis=1),
    "mkt1": ret1.median(axis=1),
    "mkt5": r5.median(axis=1),
    "mkt20": (C / C.shift(20) - 1).median(axis=1),
    "mkt60": (C / C.shift(60) - 1).median(axis=1),
    "mktvol20": ret1.median(axis=1).rolling(20, min_periods=10).std(),
    "disp": ret1.std(axis=1),
}
for k, ser in mk.items():
    feats[k] = pd.DataFrame(
        np.broadcast_to(ser.to_numpy()[:, None], (T, S)).astype("float32"),
        index=C.index,
        columns=C.columns,
    )

OWN = [f for f in ro.FEATURES if f not in ("rs20", "rs60")] + [
    "vol20",
    "atr14",
    "up_days10",
    "r5_z",
]  # the stock's own history only: nothing about other stocks
MKT = list(mk)

fwd5 = C.shift(-5) / C - 1
ok = ro.liquid(p) & ~ro._split_mask(p, splits, 70, 10) & fwd5.notna()
liq = ok.to_numpy()
day = np.nonzero(liq)[0]
dates = idx[day]
f5 = fwd5.to_numpy()[liq]
pace = feats["pace60"].to_numpy()[liq]
y_u = (f5 > 0).astype(np.int8)
valid_z = ~np.isnan(pace)
y_z = (f5 > pace).astype(np.int8)
ex = ro.excess(p, splits).to_numpy()[liq]
y_rel = (ex > 0).astype(np.int8)


def stack(names: list[str]) -> np.ndarray:
    x = np.column_stack([feats[k].to_numpy()[liq] for k in names]).astype("float32")
    x[~np.isfinite(x)] = np.nan
    return x


def hgb() -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        max_iter=200,
        learning_rate=0.05,
        max_leaf_nodes=15,
        min_samples_leaf=800,
        l2_regularization=5.0,
        random_state=0,
    )


def tails(score: np.ndarray, y: np.ndarray, d: np.ndarray) -> None:
    day_base = pd.Series(y.astype(float)).groupby(d).transform("mean").to_numpy()
    order = np.argsort(-score)
    for c in (0.01, 0.05, 0.25):
        k = max(1, int(c * len(score)))
        t, b = order[:k], order[-k:]
        print(
            f"         {100 * c:>5.1f}%  top say up: {100 * y[t].mean():5.1f}% on {len(np.unique(d[t])):>3} days (same-day lift {100 * (y[t] - day_base[t]).mean():+5.1f} pt)   bottom say down: {100 * (1 - y[b]).mean():5.1f}% (lift {100 * (day_base[b] - y[b]).mean():+5.1f} pt)"
        )


gap = np.timedelta64(30, "D")
print(f"{int(liq.sum()):,} liquid stock-days\n")
everyone = np.ones(len(y_u), dtype=bool)
for title, tr_end, te_start in (
    ("split A: train to 2022, judge 2024 onward", "2023-01-01", "2024-01-01"),
    ("split B: train to 2023, judge 2025 onward", "2024-01-01", "2025-01-01"),
):
    tr = dates < (np.datetime64(tr_end) - gap)
    te = dates >= np.datetime64(te_start)
    print(f"##### {title}: {tr.sum():,} training rows, {te.sum():,} judged")
    for tname, y, keep, sets in (
        (
            "U  closes higher in 5 sessions",
            y_u,
            everyone,
            (("own history only", OWN), ("own + market state", OWN + MKT)),
        ),
        (
            "Z  beats its own recent 5-session pace",
            y_z,
            valid_z,
            (("own history only", OWN), ("own + market state", OWN + MKT)),
        ),
        (
            "R  beats the other stocks (the rise odds target), for comparison",
            y_rel,
            ~np.isnan(ex),
            (("the rise-odds features", list(ro.FEATURES)),),
        ),
    ):
        for fname, names in sets:
            trk, tek = tr & keep, te & keep
            X = stack(names)
            fit_rows = np.nonzero(trk)[0][::2]
            m = hgb().fit(X[fit_rows], y[fit_rows])
            s = m.predict_proba(X[tek])[:, 1]
            yt, dt = y[tek], day[tek]
            years = pd.Series(dates[tek]).dt.year.to_numpy()
            by_year = ", ".join(
                f"{yr}: {roc_auc_score(yt[years == yr], s[years == yr]):.3f}"
                for yr in sorted(set(years))
            )
            print(f"   {tname}  [{fname}]")
            print(
                f"      AUC {roc_auc_score(yt, s):.4f}  (by year {by_year});  base rate {100 * yt.mean():.1f}%"
            )
            tails(s, yt, dt)
            # what the most confident picks actually did, in plain terms: did they rise, by how much, and what was the bar they had to clear
            order = np.argsort(-s)
            for c in (0.01, 0.05):
                k = max(1, int(c * len(s)))
                t = order[:k]
                pace_t = pace[tek][t]
                print(
                    f"         top {100 * c:.0f}% picks actually: rose {100 * (f5[tek][t] > 0).mean():5.1f}% of the time (all stocks {100 * (f5[tek] > 0).mean():.1f}%), mean 5-session move {100 * f5[tek][t].mean():+.2f}% (all {100 * f5[tek].mean():+.2f}%), the pace they had to beat averaged {100 * np.nanmean(pace_t):+.2f}% (all {100 * np.nanmean(pace[tek]):+.2f}%)"
                )
    print()
