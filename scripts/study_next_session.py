# ruff: noqa: E501
"""Next-session direction study (2026-11-19). RESEARCH ONLY; no product use. DEFINITIONS FROZEN BEFORE THE FIRST RUN.

Question: from what is known after today's close, can a model call the NEXT trading session's closing direction of an NSE stock better than simple baselines, and is that edge calibrated, stable and
economically useful?
FROZEN: target r = (close[t+1] + dividend with ex-date t+1) / close[t] - 1, t+1 = the next market session (a missing bar = no observation). UP r > +0.10%, DOWN r < -0.10%, FLAT otherwise (the band is about the
cost of a tick on a mid-priced stock and was fixed before any model ran; it is not tuned). Binary UP/DOWN evaluation excludes FLAT and reports the excluded share.
Data: bars STRICTLY BEFORE 2024-01-01 (the protected holdout is 2025-01-01..2026-11-13 by config/research_holdout.json and the brief says 2024+; the stricter bound is used and the query itself cuts there).
Walk-forward, expanding: train on every day before the validation year minus 1 session (purge), validate on 2021, 2022, 2023. Nothing is fitted, imputed, scaled or selected on validation rows.
Universe: liquid stocks (20-day mean turnover >= Rs 5 crore, known at t) with a bar on t and t+1; windows around splits, bonuses, demergers, mergers, rights and other price-changing actions are dropped (+-25 / +22 sessions).
Feature groups (all computed from completed daily bars of t or earlier): A price, B candle, C momentum/trend, D volume (+ delivery %, published in the evening: tested separately as D without delivery),
E market (Nifty, breadth, India VIX), F sector (retroactive, see below), G volatility. Models, hyperparameters FIXED (no tuning): logistic regression, random forest, histogram gradient boosting (scikit-learn; xgboost / lightgbm / catboost are
not installed and are not added without approval). Baselines: majority class, persistence (same direction as today), reversal, Nifty's direction today.
LIMITATION (documented, not hidden): instrument_sector holds ONE snapshot (2026-11-10, 497 current Nifty 500 stocks). No point-in-time sector history exists, so group F is a retroactive mapping on that subset only and is
compared against a price-only model on the SAME subset. The current Nifty 500 are also survivors. "Large vs small cap" is proxied by liquidity tercile.
Significance: per-day sums, circular block bootstrap over days (block 10, 1000 draws): observations on one day are strongly dependent. Every configuration is logged; the Bonferroni count is printed.
usage: study_next_session.py [--db URL] [--log register.csv] [--preds preds.npz]"""

import argparse
import math
import os
import sys
from statistics import NormalDist

import numpy as np
import pandas as pd
import psycopg
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from study_common import BARS  # noqa: E402,I001

from algo.research import next_session_features as ns

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--min-turnover-cr", type=float, default=5.0)
ap.add_argument(
    "--train-rows", type=int, default=250_000, help="random training rows per fit (fixed seed)"
)
ap.add_argument("--log", help="write the experiment register (every config x fold) to this CSV")
ap.add_argument(
    "--preds", help="save every validation prediction (rows, probabilities) to this .npz"
)
ap.add_argument(
    "--cost-pct", type=float, default=0.25, help="round-trip cost for the economic table"
)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
FLAT = ns.FLAT
END = "2024-01-01"
FOLDS = {"V2021": 2021, "V2022": 2022, "V2023": 2023}
THRESH = (0.55, 0.60, 0.65, 0.70)

with psycopg.connect(a.db) as conn:
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, open::float8, high::float8, low::float8, close::float8, volume::float8, delivery_qty::float8"
        f" FROM {BARS} WHERE source='kite' AND ts >= '2019-01-01' AND (ts AT TIME ZONE 'Asia/Kolkata')::date < %s ORDER BY instrument_id, ts, dataset_version DESC",
        (END,),
    ).fetchall()
    acts = conn.execute(
        "SELECT instrument_id, ex_date, kind, amount::float8 FROM corporate_action WHERE ex_date >= '2019-01-01' AND ex_date < %s",
        (END,),
    ).fetchall()
    nifty = conn.execute(
        "SELECT trade_date, close::float8 FROM index_bar_1d WHERE symbol='NIFTY 50' AND trade_date >= '2018-06-01' AND trade_date < %s ORDER BY trade_date",
        (END,),
    ).fetchall()
    vix = conn.execute(
        "SELECT trade_date, close::float8 FROM index_bar_1d WHERE symbol='INDIA VIX' AND trade_date >= '2018-06-01' AND trade_date < %s ORDER BY trade_date",
        (END,),
    ).fetchall()
    sect = conn.execute("SELECT instrument_id, sector FROM instrument_sector").fetchall()
    dead = {
        int(r[0])
        for r in conn.execute("SELECT instrument_id FROM instrument WHERE delisted_on IS NOT NULL")
    }

df = pd.DataFrame(rows, columns=["iid", "d", "o", "h", "l", "c", "v", "dq"])
del rows
df["d"] = pd.to_datetime(df["d"])
O, H, L, C, V, DQ = (  # noqa: E741
    df.pivot(index="d", columns="iid", values=k).sort_index()
    for k in ("o", "h", "l", "c", "v", "dq")
)
del df
T, S = C.shape
idx = C.index.values
assert idx.max() < np.datetime64(END)
NF = pd.Series({pd.Timestamp(d): x for d, x in nifty}).reindex(C.index, method="ffill")
VX = pd.Series({pd.Timestamp(d): x for d, x in vix}).reindex(C.index, method="ffill")
col = {int(c): j for j, c in enumerate(C.columns)}

# ---------------------------------------------------------------- target (dividend added back on the ex-date) and exclusions
DIV, bad = ns.corporate_action_masks(idx, list(C.columns), acts)
pc = C.shift(1)
r1 = ns.next_session_return(C, DIV)
cls = np.where(r1 > FLAT, 2, np.where(r1 < -FLAT, 0, 1)).astype(np.int8)  # 0 DOWN, 1 FLAT, 2 UP

# ---------------------------------------------------------------- features (every one uses bars of t or earlier)
sec = pd.Series(dict(sect)).reindex(C.columns)
F, aux = ns.build_features(O, H, L, C, V, DQ, NF, VX, sec)
atr, ret, nr = aux["atr"], aux["ret"], aux["nr"]
mk_up, mk_dn, vix_hi, has_sec = aux["mk_up"], aux["mk_dn"], aux["vix_hi"], aux["has_sec"]
turn = aux["turn"]
ok = (
    (turn >= a.min_turnover_cr).to_numpy()
    & ~bad
    & np.isfinite(r1)
    & np.isfinite(ret[10].to_numpy())
    & np.isfinite(atr.to_numpy())
    & (idx > np.datetime64("2019-12-31"))[:, None]
)
ti, sj = np.nonzero(ok)
print(
    f"{S} stocks ({len(dead & set(col))} delisted), {T} sessions to {str(idx[-1])[:10]} (nothing from 2024 on is read); {len(ti):,} eligible stock-days; FLAT share {100 * (cls[ok] == 1).mean():.1f}% (band +-{100 * FLAT:.2f}%)"
)

NAMES: list[str] = []
cols: list[np.ndarray] = []
GROUP_OF: dict[str, str] = {}
for g, d in F.items():
    for nm, arr in d.items():
        a2 = arr.to_numpy(dtype=np.float32) if isinstance(arr, pd.DataFrame) else arr
        v = a2[ti, sj].astype(np.float32)
        v[~np.isfinite(v)] = np.nan
        NAMES.append(nm)
        cols.append(v)
        GROUP_OF[nm] = g
X = np.column_stack(cols)
del cols
y3 = cls[ti, sj]
rr = r1[ti, sj]
dayi = ti
yr = (idx.astype("datetime64[Y]").astype(int) + 1970)[ti]
hassec = has_sec[sj]
liq = np.log10(turn.clip(lower=1e-3).to_numpy(dtype=np.float32)[ti, sj])
nup, ndn, vhi = mk_up[ti], mk_dn[ti], vix_hi[ti]
prev_dir = np.sign(ret[1].to_numpy(dtype=np.float32)[ti, sj])
nday_dir = np.sign(nr[1].to_numpy(dtype=np.float32)[ti])
isdead = np.array([int(c) in dead for c in C.columns])[sj]
del F
print(
    f"{len(NAMES)} features in groups "
    + ", ".join(
        f"{g}={sum(1 for n in NAMES if GROUP_OF[n] == g)}" for g in "A B C D0 Dd E F G".split()
    )
)

GROUPS = {
    "A": ["A"],
    "AB": ["A", "B"],
    "AC": ["A", "C"],
    "AD": ["A", "D0", "Dd"],
    "AD0": ["A", "D0"],
    "AE": ["A", "E"],
    "ALL": ["A", "B", "C", "D0", "Dd", "E", "G"],
    "AF": ["A", "F"],
    "ALLF": ["A", "B", "C", "D0", "Dd", "E", "F", "G"],
}


def cols_of(gs: list[str]) -> np.ndarray:
    return np.array([i for i, n in enumerate(NAMES) if GROUP_OF[n] in gs])


def make(model: str):
    if model == "LR":
        return make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            LogisticRegression(C=1.0, max_iter=200),
        )
    if model == "RF":
        return make_pipeline(
            SimpleImputer(strategy="median"),
            RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                min_samples_leaf=200,
                max_samples=0.5,
                n_jobs=3,
                random_state=0,
            ),
        )
    return HistGradientBoostingClassifier(
        max_iter=150,
        learning_rate=0.08,
        max_leaf_nodes=31,
        min_samples_leaf=200,
        l2_regularization=1.0,
        early_stopping=False,
        random_state=0,
    )


# ---------------------------------------------------------------- experiments
REG: list[dict] = []
PRED: dict[
    tuple[str, str], tuple[np.ndarray, np.ndarray]
] = {}  # (model, set) -> (row ids, p(3 classes))
rng_ = np.random.default_rng(0)
CONFIGS: list[tuple[str, str, bool]] = []  # model, set name, subset?
for m in ("LR", "HGB"):
    for s in ("A", "AB", "AC", "AD", "AD0", "AE", "ALL"):
        CONFIGS.append((m, s, False))
    for s in ("A", "AF", "ALL", "ALLF"):
        CONFIGS.append((m, s, True))
for s in ("A", "ALL"):
    CONFIGS.append(("RF", s, False))
for s in ("A", "ALL", "ALLF"):
    CONFIGS.append(("RF", s, True))
print(
    f"{len(CONFIGS)} model configurations x {len(FOLDS)} folds, all logged; hyperparameters fixed"
)

fold_first = {k: int(np.searchsorted(idx, np.datetime64(f"{y}-01-01"))) for k, y in FOLDS.items()}
for model, sname, sub in CONFIGS:
    key = (model, sname + ("@sec" if sub else ""))
    cj = cols_of(GROUPS[sname])
    ids, probs = [], []
    for fk, fy in FOLDS.items():
        base = hassec if sub else np.ones(len(ti), dtype=bool)
        trm = base & (dayi < fold_first[fk] - 1)
        vam = base & (yr == fy)
        tr_ids = np.flatnonzero(trm)
        if len(tr_ids) > a.train_rows:
            tr_ids = rng_.choice(tr_ids, a.train_rows, replace=False)
        mdl = make(model).fit(X[tr_ids][:, cj], y3[tr_ids])
        va_ids = np.flatnonzero(vam)
        pr = mdl.predict_proba(X[va_ids][:, cj])
        full = np.zeros((len(va_ids), 3), dtype=np.float32)
        full[:, list(mdl.classes_)] = pr
        ids.append(va_ids)
        probs.append(full)
    PRED[key] = (np.concatenate(ids), np.concatenate(probs))
    print(f"  fitted {key[0]:<4}{key[1]:<10} validation rows {len(PRED[key][0]):,}", flush=True)

# ---------------------------------------------------------------- metrics
rngb = np.random.default_rng(1)


def block_idx(nd: int, block: int, draws: int) -> np.ndarray:
    nb = math.ceil(nd / block)
    st = rngb.integers(0, nd, (draws, nb))
    return ((st[:, :, None] + np.arange(block)) % nd).reshape(draws, -1)[:, :nd]


def boot_ratio(
    s: np.ndarray, n: np.ndarray, block: int = 10, draws: int = 1000
) -> tuple[float, float, float]:
    keep = n > 0
    s, n = s[keep], n[keep]
    if len(n) < 20:
        return float("nan"), float("nan"), float("nan")
    ix = block_idx(len(n), block, draws)
    v = s[ix].sum(1) / np.maximum(n[ix].sum(1), 1)
    return float(np.quantile(v, 0.025)), float(np.quantile(v, 0.975)), float(v.std())


def day_sums(ids: np.ndarray, val: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    d = dayi[ids]
    return np.bincount(d, weights=val, minlength=T), np.bincount(d, minlength=T).astype(float)


def binp(p3: np.ndarray) -> np.ndarray:
    return p3[:, 2] / np.maximum(p3[:, 2] + p3[:, 0], 1e-9)


def ece_of(p: np.ndarray, yb: np.ndarray, bins: int = 10) -> tuple[float, float]:
    q = np.quantile(p, np.linspace(0, 1, bins + 1))
    b = np.clip(np.digitize(p, q[1:-1]), 0, bins - 1)
    gaps = [
        (abs(p[b == k].mean() - yb[b == k].mean()), (b == k).sum())
        for k in range(bins)
        if (b == k).any()
    ]
    return sum(g * n for g, n in gaps) / sum(n for _, n in gaps), max(g for g, _ in gaps)


def metrics(ids: np.ndarray, p3: np.ndarray) -> dict:
    y = y3[ids]
    pred3 = p3.argmax(1)
    m = {
        "n3": len(ids),
        "acc3": float((pred3 == y).mean()),
        "bacc3": float(balanced_accuracy_score(y, pred3)),
        "flat_share": float((y == 1).mean()),
    }
    nf = y != 1
    pb, yb = np.clip(binp(p3[nf]), 1e-6, 1 - 1e-6), (y[nf] == 2).astype(float)
    pu = pb >= 0.5
    m.update(
        n2=int(nf.sum()),
        acc2=float((pu == (yb == 1)).mean()),
        bacc2=float(balanced_accuracy_score(yb, pu)),
        up_rate=float(yb.mean()),
        brier=float(((pb - yb) ** 2).mean()),
        logloss=float(-(yb * np.log(pb) + (1 - yb) * np.log(1 - pb)).mean()),
    )
    m["up_prec"] = float(yb[pu].mean()) if pu.any() else float("nan")
    m["up_rec"] = float(pu[yb == 1].mean())
    m["dn_prec"] = float(1 - yb[~pu].mean()) if (~pu).any() else float("nan")
    m["dn_rec"] = float((~pu)[yb == 0].mean())
    m["ece"], m["max_gap"] = ece_of(pb, yb)
    return m


for (model, sname), (ids, p3) in PRED.items():
    for fk, fy in list(FOLDS.items()) + [("ALL", 0)]:
        sel = np.ones(len(ids), dtype=bool) if fk == "ALL" else yr[ids] == fy
        REG.append({"model": model, "set": sname, "fold": fk, **metrics(ids[sel], p3[sel])})
R = pd.DataFrame(REG)

print(
    "\n=== 1. BASELINES (binary UP/DOWN, FLAT excluded) on the validation rows of the full-universe sets"
)
ids0 = PRED[("LR", "A")][0]
tr_up = {fk: float((y3[(dayi < fold_first[fk] - 1) & (y3 != 1)] == 2).mean()) for fk in FOLDS}
for fk, fy in list(FOLDS.items()) + [("ALL", 0)]:
    inyr = (yr[ids0] == fy) if fk != "ALL" else np.ones(len(ids0), dtype=bool)
    ii = ids0[(y3[ids0] != 1) & inyr]
    yb = y3[ii] == 2
    maj = (np.mean(list(tr_up.values())) if fk == "ALL" else tr_up[fk]) >= 0.5
    print(
        f"{fk:<6} n={len(ii):>8,}  up-rate {100 * yb.mean():5.2f}%  majority(train) {100 * (yb == maj).mean():5.2f}%  persistence {100 * ((prev_dir[ii] > 0) == yb)[prev_dir[ii] != 0].mean():5.2f}%  reversal {100 * ((prev_dir[ii] < 0) == yb)[prev_dir[ii] != 0].mean():5.2f}%  Nifty-today {100 * ((nday_dir[ii] > 0) == yb)[nday_dir[ii] != 0].mean():5.2f}%  FLAT share of all rows {100 * (y3[ids0] == 1)[inyr].mean():.1f}%"
    )

print(
    "\n=== 2. MODELS x FEATURE SETS, pooled over 2021-2023 (binary: accuracy, balanced accuracy, Brier, log loss, ECE, largest decile gap; 3-class accuracy and balanced accuracy; n)"
)
P = R[R.fold == "ALL"]
print(
    f"{'model':<5}{'set':<10}{'acc2':>7}{'bacc2':>7}{'brier':>8}{'logloss':>9}{'ECE':>7}{'maxgap':>8}{'acc3':>7}{'bacc3':>7}{'n2':>9}"
)
for _, r in P.iterrows():
    print(
        f"{r.model:<5}{r.set:<10}{100 * r.acc2:7.2f}{100 * r.bacc2:7.2f}{r.brier:8.5f}{r.logloss:9.5f}{100 * r.ece:7.2f}{100 * r.max_gap:8.2f}{100 * r.acc3:7.2f}{100 * r.bacc3:7.2f}{int(r.n2):>9,}"
    )

print("\n=== 3. BY YEAR (binary accuracy %, balanced accuracy %)")
for model, sname in [("LR", "A"), ("LR", "ALL"), ("HGB", "A"), ("HGB", "ALL"), ("RF", "ALL")]:
    q = R[(R.model == model) & (R.set == sname) & (R.fold != "ALL")]
    print(
        f"{model:<4}{sname:<8}"
        + "  ".join(f"{r.fold} {100 * r.acc2:5.2f}/{100 * r.bacc2:5.2f}" for _, r in q.iterrows())
    )

print(
    "\n=== 4. INCREMENTAL VALUE: change in binary log loss against the reference set on the SAME rows (negative = better), 95% day-block CI; z = mean / bootstrap sd"
)
Z: list[tuple[str, float]] = []


def loss_vec(ids: np.ndarray, p3: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    nf = y3[ids] != 1
    pb = np.clip(binp(p3[nf]), 1e-6, 1 - 1e-6)
    yb = (y3[ids][nf] == 2).astype(float)
    return ids[nf], -(yb * np.log(pb) + (1 - yb) * np.log(1 - pb))


for model in ("LR", "HGB", "RF"):
    for sname, ref in (
        ("AB", "A"),
        ("AC", "A"),
        ("AD", "A"),
        ("AD0", "A"),
        ("AE", "A"),
        ("ALL", "A"),
        ("AF@sec", "A@sec"),
        ("ALL@sec", "A@sec"),
        ("ALLF@sec", "ALL@sec"),
    ):
        if (model, sname) not in PRED or (model, ref) not in PRED:
            continue
        i1, l1 = loss_vec(*PRED[(model, sname)])
        i0, l0 = loss_vec(*PRED[(model, ref)])
        assert np.array_equal(i1, i0)
        s_, n_ = day_sums(i1, l1 - l0)
        mean = float(s_.sum() / n_.sum())
        lo, hi, sd = boot_ratio(s_, n_)
        z = mean / sd
        Z.append((f"{model} {sname} vs {ref}", z))
        print(
            f"{model:<4}{sname:<10} vs {ref:<8} dlogloss {mean:+.5f} [{lo:+.5f},{hi:+.5f}] z {z:+5.1f}"
        )
zc = NormalDist().inv_cdf(1 - 0.05 / 2 / max(len(Z), 1))
print(
    f"{len(Z)} paired comparisons; Bonferroni |z| >= {zc:.2f}. Significantly BETTER than the reference: "
    + (", ".join(f"{k} (z {z:+.1f})" for k, z in Z if z <= -zc) or "none")
)

print(
    "\n=== 5. SELECTIVE PREDICTION: binary confidence = max(P(up), P(down)) after renormalising without FLAT; the full threshold table, no best-threshold picking"
)
for model, sname in [("LR", "ALL"), ("HGB", "ALL"), ("RF", "ALL"), ("HGB", "A")]:
    ids, p3 = PRED[(model, sname)]
    nf = y3[ids] != 1
    ii, pb = ids[nf], binp(p3[nf])
    yb = y3[ii] == 2
    conf = np.maximum(pb, 1 - pb)
    pu = pb >= 0.5
    print(f"-- {model} {sname}: all eligible binary rows n={len(ii):,}")
    print(
        f"{'conf>=':>7}{'n':>9}{'coverage':>9}{'acc':>7}{'95% CI':>16}{'UP-calls':>9}{'acc':>7}{'DOWN-calls':>11}{'acc':>7}   by year (2021/22/23 acc %, n)"
    )
    for th in (0.50,) + THRESH:
        m = conf >= th
        if m.sum() < 50:
            print(f"{th:7.2f}{int(m.sum()):>9,}  too few")
            continue
        c = (pu == yb)[m]
        s_, n_ = day_sums(ii[m], c.astype(float))
        lo, hi, _ = boot_ratio(s_, n_)
        u, d_ = m & pu, m & ~pu
        yrs = "  ".join(
            f"{100 * (pu == yb)[m & (yr[ii] == y)].mean():5.1f}%/{int((m & (yr[ii] == y)).sum()):>6,}"
            if (m & (yr[ii] == y)).sum() > 30
            else "    -"
            for y in (2021, 2022, 2023)
        )
        print(
            f"{th:7.2f}{int(m.sum()):>9,}{100 * m.mean():8.2f}%{100 * c.mean():7.2f}  [{100 * lo:5.1f},{100 * hi:5.1f}]{int(u.sum()):>9,}{100 * (yb[u]).mean() if u.any() else float('nan'):7.1f}{int(d_.sum()):>11,}{100 * (~yb[d_]).mean() if d_.any() else float('nan'):7.1f}   {yrs}"
        )

print(
    "\n=== 6. CALIBRATION (binary P(up) deciles, pooled 2021-2023): predicted -> observed up-rate %"
)
for model, sname in [("LR", "ALL"), ("HGB", "ALL")]:
    ids, p3 = PRED[(model, sname)]
    nf = y3[ids] != 1
    pb, yb = binp(p3[nf]), (y3[ids][nf] == 2).astype(float)
    yy = yr[ids][nf]
    q = np.quantile(pb, np.linspace(0, 1, 11))
    b = np.clip(np.digitize(pb, q[1:-1]), 0, 9)
    print(
        f"-- {model} {sname}: "
        + "  ".join(
            f"{100 * pb[b == k].mean():.1f}->{100 * yb[b == k].mean():.1f}" for k in range(10)
        )
    )
    print(
        "   mean predicted minus observed up-rate by year: "
        + ", ".join(
            f"{y_} {100 * (pb[yy == y_].mean() - yb[yy == y_].mean()):+.2f}pp"
            for y_ in (2021, 2022, 2023)
        )
    )

print(
    f"\n=== 7. ECONOMIC CHECK: hold UP calls at or above the threshold from today's close to tomorrow's close, equal weight, cost {a.cost_pct}% round trip per trade; DOWN calls shown gross only (overnight short selling of cash equities is not generally available)"
)
days_val = np.array([t for t in range(T) if idx[t] >= np.datetime64("2021-01-01")])
for model in ("HGB", "LR"):
    ids, p3 = PRED[(model, "ALL")]
    nf = y3[ids] != 1
    ii0, pb0 = ids[nf], binp(p3[nf])
    print(
        f"-- {model} ALL  thr   trades  gross%/trade  net%/trade  days  net daily%  ann.Sharpe  maxDD   DOWN-call gross%/trade"
    )
    for th in THRESH:
        m = pb0 >= th
        if m.sum() < 100:
            print(f"   {th:.2f}  too few")
            continue
        ii = ii0[m]
        g = rr[ii]
        cnt = np.bincount(dayi[ii], minlength=T)
        daily = np.bincount(dayi[ii], weights=g - a.cost_pct / 100, minlength=T) / np.maximum(
            cnt, 1
        )
        series = np.where(cnt > 0, daily, 0.0)[days_val]
        eq = np.cumprod(1 + series)
        dd = float((eq / np.maximum.accumulate(eq) - 1).min())
        sh = (
            float(series.mean() / series.std() * math.sqrt(252))
            if series.std() > 0
            else float("nan")
        )
        dm = (1 - pb0) >= th
        dg = rr[ii0[dm]].mean() * 100 if dm.sum() > 100 else float("nan")
        print(
            f"   {th:.2f}  {int(m.sum()):>7,}  {100 * g.mean():+10.3f}  {100 * g.mean() - a.cost_pct:+9.3f}  {int((cnt > 0).sum()):>5}  {100 * series.mean():+9.4f}  {sh:+9.2f}  {100 * dd:6.1f}%   {dg:+.3f}"
        )

print(
    "\n=== 8. STABILITY (HGB ALL): binary accuracy and the up-rate by year, Nifty regime, VIX regime, liquidity tercile; and accuracy at confidence >= 0.60"
)
ids, p3 = PRED[("HGB", "ALL")]
nf = y3[ids] != 1
ii, pb = ids[nf], binp(p3[nf])
yb = y3[ii] == 2
ok_ = (pb >= 0.5) == yb
cf = np.maximum(pb, 1 - pb)
qs = np.quantile(liq[ii], [1 / 3, 2 / 3])
grp = {f"year {y}": yr[ii] == y for y in (2021, 2022, 2023)} | {
    "Nifty up": nup[ii],
    "Nifty down": ndn[ii],
    "Nifty sideways": ~nup[ii] & ~ndn[ii],
    "VIX high": vhi[ii],
    "VIX low": ~vhi[ii],
    "liquidity low (small)": liq[ii] < qs[0],
    "liquidity mid": (liq[ii] >= qs[0]) & (liq[ii] < qs[1]),
    "liquidity high (large)": liq[ii] >= qs[1],
}
for g_, m in grp.items():
    h6 = m & (cf >= 0.60)
    print(
        f"{g_:<24} acc {100 * ok_[m].mean():5.2f}%  up-rate {100 * yb[m].mean():5.2f}%  n={int(m.sum()):>8,}   conf>=0.60: {100 * ok_[h6].mean() if h6.sum() > 50 else float('nan'):5.1f}% (n={int(h6.sum()):,})"
    )

print("\n=== 9. DATA QUALITY")
print(
    f"eligible stock-days {len(ti):,}; delisted-stock share {100 * isdead.mean():.2f}% of rows; sector-subset share {100 * hassec.mean():.1f}% of rows (instrument_sector is one 2026-11-10 snapshot of 497 current stocks: retroactive and survivor-biased)"
)
for fk, fy in FOLDS.items():
    print(
        f"{fk}: train rows {int((dayi < fold_first[fk] - 1).sum()):,}, validation rows {int((yr == fy).sum()):,}, stocks {len(np.unique(sj[yr == fy])):,}"
    )

if a.log:
    R.to_csv(a.log, index=False)
    print(
        f"\nexperiment register: {len(R)} rows ({len(CONFIGS)} configurations x {len(FOLDS) + 1} views) -> {a.log}"
    )
if a.preds:
    np.savez_compressed(
        a.preds,
        **{f"{k[0]}__{k[1]}__ids": v[0] for k, v in PRED.items()},
        **{f"{k[0]}__{k[1]}__p": v[1] for k, v in PRED.items()},
        day=dayi,
        stock=sj,
        r=rr,
        cls=y3,
    )
    print(f"predictions saved to {a.preds}")
