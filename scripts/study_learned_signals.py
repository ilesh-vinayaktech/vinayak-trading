# ruff: noqa: E501
"""Study: if we stop choosing the signs by hand, can a model learn from history which combinations of leading signs precede a rise?

Features known at each stock-day's close (about 30): returns over 1/5/20/60 days, volume against its 20-day norm (today and the last 5 days), delivery % and its norm,
the bar's range and where it closed in it, distance from the 52-week high and low, gaps to the 50/200-day averages and the 50-day slope, RSI, MACD histogram, Bollinger band
width against its 120-day mean, 20-day volatility, turnover, and the market's breadth (share of stocks above their 50-day average, median 20-day return) with the stock's strength
against it. Target: the stock beats the median stock that day over the next H sessions. Gradient boosting, trained on 2019-2022, number of trees chosen on 2023, judged only on
2024 onward (a gap of 2H sessions at each boundary so no training window overlaps what it is judged on). A second split trains to 2023 and judges 2025 onward.
Prints AUC (0.5 = no skill), then the test rows split by the model's own confidence: does the top 1% / 5% / 10% really beat the market more often, and by how much?
usage: study_learned_signals.py [--db URL] [--horizon 5] [--min-turnover-cr 5]"""

import argparse
import os
import sys

import numpy as np
import pandas as pd
import psycopg
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import roc_auc_score
from study_common import BARS  # noqa: E402,I001

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--horizon", type=int, default=5)
ap.add_argument("--min-turnover-cr", type=float, default=5.0)
ap.add_argument(
    "--drop",
    default="",
    help="comma-separated features to leave out (e.g. vol20,lturn,breadth,mkt20,mkt60 to leave out what kind of stock it is and the market backdrop)",
)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
HZ = a.horizon

with psycopg.connect(a.db) as conn:
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, high::float8, low::float8, close::float8, volume::float8, delivery_qty::float8"
        f" FROM {BARS} WHERE source='kite' AND ts >= '2019-09-01' ORDER BY instrument_id, ts, dataset_version DESC"
    ).fetchall()
    splits = conn.execute(
        "SELECT instrument_id, ex_date FROM corporate_action WHERE kind IN ('split','bonus') AND status='ok'"
    ).fetchall()
df = pd.DataFrame(rows, columns=["iid", "d", "h", "l", "c", "v", "dq"])
del rows


def mat(frame: pd.DataFrame, col: str) -> pd.DataFrame:
    return frame.pivot(index="d", columns="iid", values=col).sort_index().astype("float32")


H, L, C, V, DQ = (mat(df, k) for k in ("h", "l", "c", "v", "dq"))
del df
T, S = C.shape
R = H - L
sma20, sma50, sma200 = (C.rolling(n, min_periods=n).mean() for n in (20, 50, 200))
sd20 = C.rolling(20, min_periods=20).std()
bw = 4 * sd20 / sma20
dpct = DQ / V.where(V > 0) * 100
ema12, ema26 = C.ewm(span=12, adjust=False).mean(), C.ewm(span=26, adjust=False).mean()
macd = ema12 - ema26
dl = C.diff()
rsi = 100 - 100 / (
    1
    + dl.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    / (-dl.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
)
ret = C.pct_change()
r20, r60 = C / C.shift(20) - 1, C / C.shift(60) - 1
breadth = (
    (C > sma50).where(sma50.notna()).mean(axis=1)
)  # the share of stocks above their 50-day average, each day
mkt20 = r20.median(axis=1)
mkt60 = r60.median(axis=1)

feat: dict[str, pd.DataFrame] = {
    "r1": C / C.shift(1) - 1,
    "r5": C / C.shift(5) - 1,
    "r20": r20,
    "r60": r60,
    "vr1": V / V.shift(1).rolling(20, min_periods=15).mean(),
    "vr5": V.rolling(5).mean() / V.shift(5).rolling(20, min_periods=15).mean(),
    "dpct": dpct,
    "dpct5": DQ.rolling(5).sum() / V.rolling(5).sum() * 100,
    "dratio": dpct / dpct.shift(1).rolling(20, min_periods=15).mean(),
    "rng": R / R.shift(1).rolling(14, min_periods=14).mean(),
    "loc": (C - L) / R.where(R > 0),
    "d52h": C / C.rolling(252, min_periods=200).max() - 1,
    "d52l": C / C.rolling(252, min_periods=200).min() - 1,
    "g50": C / sma50 - 1,
    "g200": C / sma200 - 1,
    "slope50": sma50 / sma50.shift(10) - 1,
    "rsi": rsi,
    "macdh": (macd - macd.ewm(span=9, adjust=False).mean()) / C * 100,
    "bwr": bw / bw.rolling(120, min_periods=60).mean(),
    "vol20": ret.rolling(20, min_periods=15).std() * 100,
    "lturn": np.log((C * V).rolling(20, min_periods=15).mean() / 1e7 + 1e-9),
    "rs20": r20.sub(mkt20, axis=0),
    "rs60": r60.sub(mkt60, axis=0),
}
for name, ser in (("breadth", breadth), ("mkt20", mkt20), ("mkt60", mkt60)):
    feat[name] = pd.DataFrame(
        np.broadcast_to(ser.to_numpy()[:, None], (T, S)).astype("float32"),
        index=C.index,
        columns=C.columns,
    )
for dropped in [d for d in a.drop.split(",") if d]:
    feat.pop(dropped)
NAMES = list(feat)

turnover = (C * V).rolling(20, min_periods=15).mean() / 1e7
fwd = C.shift(-HZ) / C - 1
bad = pd.DataFrame(False, index=C.index, columns=C.columns)
idx = C.index.values
for iid, ex_date in splits:
    if iid in bad.columns:
        i = int(np.searchsorted(idx, np.datetime64(ex_date)))
        bad.iloc[max(0, i - 70) : min(T, i + HZ + 1), bad.columns.get_loc(iid)] = (
            True  # 70: the longest look-back (60 sessions) must not cross a split either
        )
liquid = ((turnover >= a.min_turnover_cr) & ~bad & fwd.notna()).to_numpy()
ex = fwd.sub(fwd.where(liquid).median(axis=1), axis=0).to_numpy()

day = np.nonzero(liquid)[0]
X = np.column_stack([feat[k].to_numpy()[liquid] for k in NAMES]).astype("float32")
y = (ex[liquid] > 0).astype(np.int8)
exv = ex[liquid]
dates = idx[day]
del feat
ok = ~np.isnan(X).all(axis=1)
X, y, exv, dates, day = X[ok], y[ok], exv[ok], dates[ok], day[ok]
print(
    f"horizon {HZ} sessions: {len(y):,} liquid stock-days with features, {len(NAMES)} features; {100 * y.mean():.1f}% beat the median stock (a coin flip is 50)\n"
)

gap = np.timedelta64(2 * HZ + 10, "D")


def run(train_end: str, val_end: str, label: str) -> None:
    tr_end, va_end = np.datetime64(train_end), np.datetime64(val_end)
    tr = dates < (tr_end - gap)
    va = (dates >= tr_end) & (dates < (va_end - gap))
    te = dates >= va_end
    print(
        f"##### {label}: train to {train_end} ({tr.sum():,} rows), choose on {train_end}..{val_end} ({va.sum():,}), judge from {val_end} ({te.sum():,})"
    )
    sub = np.nonzero(tr)[0][::2]  # every other row: neighbouring days are nearly the same example
    best, best_auc, model = 0, 0.0, None
    for n_iter in (60, 120, 240):
        m = HistGradientBoostingClassifier(
            max_iter=n_iter,
            learning_rate=0.05,
            max_leaf_nodes=15,
            min_samples_leaf=800,
            l2_regularization=5.0,
            random_state=0,
        )
        m.fit(X[sub], y[sub])
        auc = roc_auc_score(y[va], m.predict_proba(X[va])[:, 1])
        print(f"   {n_iter:>3} trees: validation AUC {auc:.4f}")
        if auc > best_auc:
            best, best_auc, model = n_iter, auc, m
    p = model.predict_proba(X[te])[:, 1]
    base_mean = exv[te].mean()
    print(
        f"   chosen: {best} trees. Judged on {te.sum():,} rows from {val_end}: AUC {roc_auc_score(y[te], p):.4f} (0.5 = no skill); a random stock beats the median {100 * y[te].mean():.1f}%, mean excess {100 * base_mean:+.2f}%"
    )
    print(
        f"   {'model confidence':<28}{'rows':>9}{'beat %':>8}{'mean excess %':>15}{'edge %':>8}{'t (by day)':>11}"
    )
    order = np.argsort(-p)
    for name, frac in (
        ("top 1%", 0.01),
        ("top 5%", 0.05),
        ("top 10%", 0.10),
        ("top 25%", 0.25),
        ("bottom 25%", -0.25),
    ):
        k = max(1, int(abs(frac) * len(p)))
        sel = order[:k] if frac > 0 else order[-k:]
        e = exv[te][sel]
        d = day[te][sel]
        cnt = np.bincount(d, minlength=T)
        tot = np.bincount(d, weights=e - base_mean, minlength=T)
        pw = tot[cnt > 0] / cnt[cnt > 0]
        t = (
            pw.mean() / (pw.std(ddof=1) / np.sqrt(len(pw)))
            if len(pw) > 5 and pw.std(ddof=1) > 0
            else float("nan")
        )
        print(
            f"   {name:<28}{k:>9,}{100 * y[te][sel].mean():>8.1f}{100 * e.mean():>15.2f}{100 * (e.mean() - base_mean):>8.2f}{t:>11.1f}"
        )
    # which features the model leans on (permutation on a sample of the validation rows: drop in AUC when one is shuffled)
    rs = np.random.default_rng(0).choice(
        np.nonzero(va)[0], size=min(60000, int(va.sum())), replace=False
    )
    pi = permutation_importance(
        model, X[rs], y[rs], scoring="roc_auc", n_repeats=2, random_state=0, n_jobs=4
    )
    top = np.argsort(-pi.importances_mean)[:10]
    print(
        "   what it leans on (drop in AUC when shuffled): "
        + ", ".join(f"{NAMES[i]} {pi.importances_mean[i]:.4f}" for i in top)
    )
    print()


run("2023-01-01", "2024-01-01", "split A")
run("2024-01-01", "2025-01-01", "split B (a later, shorter test)")
