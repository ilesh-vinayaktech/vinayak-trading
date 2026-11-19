# ruff: noqa: E501
"""Study, winners first: take every liquid stock-day that was followed by a rise of 10%+ over the next 10 sessions (a "winner") and ask what it looked like at the close before the move.

Not "how often does a sign work" (precision) but "how many of the winners did the sign catch" (recall), set against how often the same sign shows up on stock-days that did NOT rise (so a
sign common to everything is not mistaken for a cause). Every lift is measured against the SAME day's base rate, so a few strong market days cannot fake an edge.
Parts: A base rates by year; B each simple sign: coverage, recall, precision, same-day lift; C how early the winners were caught (already up 5%+ in the prior 5 sessions or not);
D the stored rise-odds model: what share of winners it had in its top 5/10/25%; E a fresh winners-first model (trained to 2022, trees chosen on 2023, judged on 2024+) and a depth-3 tree's plain rules.
usage: study_winners_first.py [--db URL] [--min-turnover-cr 5] [--gain 0.10] [--h 10]"""

import argparse
import os
import sys

import numpy as np
import pandas as pd
import psycopg
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from sklearn.tree import DecisionTreeClassifier, export_text

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--min-turnover-cr", type=float, default=5.0)
ap.add_argument("--gain", type=float, default=0.10)
ap.add_argument("--h", type=int, default=10)
ap.add_argument("--k-sigma", type=float, default=0.0, help="if set, a winner rises k times the stock's own 60-day volatility scaled to h sessions (instead of --gain)")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
HZ = a.h

with psycopg.connect(a.db) as conn:
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, high::float8, low::float8, close::float8, volume::float8, delivery_qty::float8"
        " FROM bar_1d WHERE source='nse' AND series='EQ' AND ts >= '2019-09-01' ORDER BY instrument_id, ts, dataset_version DESC"
    ).fetchall()
    splits = conn.execute("SELECT instrument_id, ex_date FROM corporate_action WHERE kind IN ('split','bonus') AND status='ok'").fetchall()
    ro = conn.execute("SELECT day, instrument_id, pct::float8 FROM rise_odds WHERE kind='rel' AND horizon=5").fetchall()
df = pd.DataFrame(rows, columns=["iid", "d", "h", "l", "c", "v", "dq"])
del rows


def mat(col: str) -> pd.DataFrame:
    return df.pivot(index="d", columns="iid", values=col).sort_index().astype("float32")


H, L, C, V, DQ = (mat(k) for k in ("h", "l", "c", "v", "dq"))
del df
T, S = C.shape
idx = C.index.values
turnover = (C * V).rolling(20, min_periods=15).mean() / 1e7
bad = pd.DataFrame(False, index=C.index, columns=C.columns)
for iid, ex_date in splits:
    if iid in bad.columns:
        i = int(np.searchsorted(idx, np.datetime64(ex_date)))
        bad.iloc[max(0, i - 260) : min(T, i + HZ + 2), bad.columns.get_loc(iid)] = True
fwd = C.shift(-HZ) / C - 1
liquid_df = (turnover >= a.min_turnover_cr) & ~bad & fwd.notna() & C.shift(-1).notna()
liq = liquid_df.to_numpy()
day_of = np.nonzero(liq)[0]  # row -> day position
iid_of = np.nonzero(liq)[1]
dts = pd.to_datetime(idx[day_of])
year = dts.year.to_numpy()
N = int(liq.sum())
if a.k_sigma:
    sig = C.pct_change().rolling(60, min_periods=40).std() * np.sqrt(HZ)  # the stock's own typical swing over HZ sessions, known at today's close
    thr_fr = a.k_sigma * sig
    liq = liq & thr_fr.notna().to_numpy()
    day_of, iid_of = np.nonzero(liq)
    dts = pd.to_datetime(idx[day_of])
    year = dts.year.to_numpy()
    N = int(liq.sum())
    W = (fwd.to_numpy()[liq] >= thr_fr.to_numpy()[liq]).astype(np.int8)
    print(f"{N:,} liquid stock-days; winner = close {HZ} sessions later is {a.k_sigma:g}+ of the stock's own typical {HZ}-session swings above today's close\n")
else:
    print(f"{N:,} liquid stock-days; winner = close {HZ} sessions later is {a.gain:.0%}+ above today's close\n")
    W = (fwd.to_numpy()[liq] >= a.gain).astype(np.int8)

# same-day base rate for every row (so a lift never rides on a few strong market days)
day_base = pd.Series(W).groupby(day_of).transform("mean").to_numpy()


def flat(fr: pd.DataFrame | np.ndarray) -> np.ndarray:
    return (fr.to_numpy() if isinstance(fr, pd.DataFrame) else fr)[liq].astype("float32")


ret1 = C.pct_change()
R = H - L
sma = {n: C.rolling(n, min_periods=n).mean() for n in (20, 50, 200)}
r5, r20, r60 = C / C.shift(5) - 1, C / C.shift(20) - 1, C / C.shift(60) - 1
dl = C.diff()
rsi = 100 - 100 / (1 + dl.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean() / (-dl.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean())
bb_sd = C.rolling(20, min_periods=20).std()
bw = 4 * bb_sd / sma[20]
bwr = bw / bw.rolling(120, min_periods=60).mean()
rng15 = (H.rolling(15).max() - L.rolling(15).min()) / C
hi20_prev = H.shift(1).rolling(20, min_periods=20).max()
hi252 = H.rolling(252, min_periods=200).max()
vm20 = V.shift(1).rolling(20, min_periods=15).mean()
vr5 = V.rolling(5).mean() / V.shift(5).rolling(20, min_periods=15).mean()
vr1 = V / vm20
dp5 = DQ.rolling(5).sum() / V.rolling(5).sum() * 100
dp20 = DQ.rolling(20, min_periods=15).sum() / V.rolling(20, min_periods=15).sum() * 100
loc = (C - L) / R.where(R > 0)
mk20 = r20.median(axis=1)
mk5 = r5.median(axis=1)
breadth50 = (C > sma[50]).where(sma[50].notna()).mean(axis=1)
bc = lambda s: pd.DataFrame(np.broadcast_to(s.to_numpy()[:, None], (T, S)), index=C.index, columns=C.columns)  # noqa: E731

cont = {
    "r1": ret1,
    "r5": r5,
    "r20": r20,
    "r60": r60,
    "rng15": rng15,
    "bwr": bwr,
    "vr1": vr1,
    "vr5": vr5,
    "dlv_gap": dp5 - dp20,
    "dpct5": dp5,
    "rsi14": rsi,
    "g50": C / sma[50] - 1,
    "g200": C / sma[200] - 1,
    "d20h": C / hi20_prev - 1,
    "d252h": C / hi252 - 1,
    "loc": loc,
    "rel20": r20 - bc(mk20),
    "rk_r20": r20.rank(axis=1, pct=True),
    "rk_vr5": vr5.rank(axis=1, pct=True),
    "mk5": bc(mk5),
    "mk20": bc(mk20),
    "breadth50": bc(breadth50),
    "lturn": np.log(turnover + 1e-9),
    "vol60": ret1.rolling(60, min_periods=40).std() * 100,
}
X ={k: flat(v) for k, v in cont.items()}

signs = {
    "sideways: 15-day range under 10%": X["rng15"] < 0.10,
    "squeeze: bands tight vs own 120d": X["bwr"] < 0.8,
    "prior 20d down (<-5%)": X["r20"] < -0.05,
    "prior 20d flat (-5..+5%)": (X["r20"] >= -0.05) & (X["r20"] <= 0.05),
    "prior 20d up (>+5%)": X["r20"] > 0.05,
    "volume today 1.5x its 20d avg": X["vr1"] > 1.5,
    "volume 5d 1.3x the prior 20d": X["vr5"] > 1.3,
    "delivery 5d above 20d by 3+ pts": X["dlv_gap"] > 3,
    "closes above prior 20d high (breakout)": X["d20h"] > 0,
    "within 10% of 52-week high": X["d252h"] > -0.10,
    "above 50 DMA": X["g50"] > 0,
    "above 200 DMA": X["g200"] > 0,
    "RSI 50-70": (X["rsi14"] >= 50) & (X["rsi14"] <= 70),
    "closes in top 30% of day range": X["loc"] > 0.7,
    "stronger than market (20d)": X["rel20"] > 0,
    "market up last 5d": X["mk5"] > 0,
}


def lift_row(mask: np.ndarray) -> tuple[int, float, float, float, float, int]:
    n = int(mask.sum())
    if n == 0:
        return 0, 0, 0, 0, 0, 0
    hit = int(W[mask].sum())
    exp = float(day_base[mask].sum())
    return n, n / N * 100, hit / W.sum() * 100, hit / n * 100, hit / exp if exp else 0, len(np.unique(day_of[mask]))


# A
print(f"=== A. base rate of winners: {W.mean() * 100:.2f}% of liquid stock-days ({int(W.sum()):,})")
for y in sorted(set(year)):
    m = year == y
    print(f"  {y}: {W[m].mean() * 100:5.2f}%  (n={int(m.sum()):,})")

# B
print("\n=== B. each sign alone (coverage = share of all stock-days; recall = share of winners that had it; precision = share of sign days that were winners; lift vs same-day base)")
print(f"{'sign':44s} {'cover%':>7s} {'recall%':>8s} {'prec%':>6s} {'lift':>5s} {'days':>5s}")
for name, m in signs.items():
    n, cov, rec, pr, lf, nd = lift_row(m)
    print(f"{name:44s} {cov:7.1f} {rec:8.1f} {pr:6.2f} {lf:5.2f} {nd:5d}")

names = list(signs)
cnt_all = sum(signs[k].astype(int) for k in names if not k.startswith("prior 20d"))
print("\n  count of signs present (excluding the three prior-20d buckets):")
print(f"  {'>=k':>5s} {'cover%':>7s} {'recall%':>8s} {'prec%':>6s} {'lift':>5s} {'days':>5s}")
for k in (3, 5, 7, 9, 11):
    n, cov, rec, pr, lf, nd = lift_row(cnt_all >= k)
    print(f"  {k:5d} {cov:7.1f} {rec:8.1f} {pr:6.2f} {lf:5.2f} {nd:5d}")

# C
print("\n=== C. how early the winners were visible")
late = X["r5"] >= 0.05
print(f"  winners already up 5%+ in the prior 5 sessions: {W[late].sum() / W.sum() * 100:.1f}% (a stock-day with that is a winner {W[late].mean() * 100:.2f}% of the time, lift {lift_row(late)[4]:.2f})")
print(f"  winners with a calm prior 5 sessions (-3%..+3%): {W[np.abs(X['r5']) <= 0.03].sum() / W.sum() * 100:.1f}%")
none = ~np.any(np.stack([signs[k] for k in names if not k.startswith("prior 20d")]), axis=0)
print(f"  winners with NONE of the signs: {W[none].sum() / W.sum() * 100:.1f}%")

# D
pct = pd.DataFrame(ro, columns=["d", "iid", "p"]).pivot(index="d", columns="iid", values="p")
pct.index = pd.to_datetime(pct.index)
pa = pct.reindex(index=pd.to_datetime(C.index), columns=C.columns).to_numpy()[liq]
print("\n=== D. the stored rise-odds model (rel, 5-day) on the winners, 2023-01 onward")
have = ~np.isnan(pa)
print(f"  pct range {np.nanmin(pa):.3f}..{np.nanmax(pa):.3f}; scored rows {int(have.sum()):,}")
scale = 100 if np.nanmax(pa) <= 1.0001 else 1
for top in (5, 10, 25):
    m = have & (pa * scale >= 100 - top)
    n, _, rec, pr, lf, nd = lift_row(m)
    wh = W[have].sum()
    print(f"  top {top:2d}%: caught {int(W[m].sum()):,} of {int(wh):,} winners = {W[m].sum() / wh * 100:5.1f}% (a random pick would catch {top}%), precision {pr:.2f}% vs base {W[have].mean() * 100:.2f}%, lift {lf:.2f}, days {nd}")

# E
print("\n=== E. fresh winners-first model: trained to 2022-11, trees chosen on 2023, judged on 2024+ (gap of 20 sessions)")
fnames = list(X)
M = np.column_stack([X[k] for k in fnames])
tr = dts < pd.Timestamp("2022-12-01")
va = (dts >= pd.Timestamp("2023-01-02")) & (dts < pd.Timestamp("2023-12-01"))
te = dts >= pd.Timestamp("2024-01-02")
clf = HistGradientBoostingClassifier(max_depth=4, learning_rate=0.05, max_iter=300, early_stopping=False, random_state=0)
best, best_auc = None, 0.0
for it in (100, 200, 300):
    clf.set_params(max_iter=it).fit(M[tr], W[tr])
    auc = roc_auc_score(W[va], clf.predict_proba(M[va])[:, 1])
    if auc > best_auc:
        best, best_auc = it, auc
clf.set_params(max_iter=best).fit(M[tr], W[tr])
p = clf.predict_proba(M[te])[:, 1]
Wt, dbt, dayt = W[te], day_base[te], day_of[te]
print(f"  trees {best}; AUC on 2023 {best_auc:.3f}, on 2024+ {roc_auc_score(Wt, p):.3f}; base rate 2024+ {Wt.mean() * 100:.2f}%")
print(f"  {'top%':>5s} {'caught of winners%':>19s} {'precision%':>11s} {'lift vs same-day':>17s} {'days':>5s}")
for top in (1, 2, 5, 10, 25):
    thr = np.quantile(p, 1 - top / 100)
    m = p >= thr
    hit, exp = int(Wt[m].sum()), float(dbt[m].sum())
    print(f"  {top:5d} {hit / Wt.sum() * 100:19.1f} {hit / m.sum() * 100:11.2f} {hit / exp:17.2f} {len(np.unique(dayt[m])):5d}")

tree = DecisionTreeClassifier(max_depth=3, min_samples_leaf=3000, class_weight="balanced", random_state=0).fit(M[tr], W[tr])
print("\n  depth-3 tree rules (train 2019-22). Leaf value = [not winner, winner] weighted:")
print(export_text(tree, feature_names=fnames, max_depth=3))
leaf_te = tree.apply(M[te])
print(f"  {'leaf':>5s} {'n':>9s} {'recall%':>8s} {'prec%':>6s} {'lift':>5s}   (2024+)")
for lf in np.unique(leaf_te):
    m = leaf_te == lf
    hit, exp = int(Wt[m].sum()), float(dbt[m].sum())
    if m.sum() >= 2000 and hit / max(exp, 1e-9) > 1.2:
        print(f"  {lf:5d} {int(m.sum()):9,d} {hit / Wt.sum() * 100:8.1f} {hit / m.sum() * 100:6.2f} {hit / exp:5.2f}")
