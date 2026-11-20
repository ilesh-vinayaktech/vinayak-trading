# ruff: noqa: E501
"""ML trend-transition study, stage 1: experiments E0 (price and volume) and E1 (+ technical structure and momentum). RESEARCH ONLY; no product use. PROTOCOL FROZEN 2026-11-19 (owner approvals the same day).

Question: can ML flag a stock that is turning from a decline into a sustained rise EARLIER and more reliably than fixed technical rules, using only what is known at the close of session T?
Two independent strategies, never pooled (definitions in algo/research/trend_transition.py):
  EARLY      base forming and not yet confirmed        CONFIRMED  breakout confirmed and not yet extended
Label (frozen): entry at the OPEN of T+1; SUCCESS = +8% reached before -4% within 20 sessions (daily highs/lows); FAILED = -4% first; UNRESOLVED = neither; AMBIGUOUS = both inside one daily candle (counted as a non-success, never assumed
favourable, excluded from training); INCOMPLETE = a needed bar is missing (excluded). Prediction timestamp: after the close of T (prices, volume; nothing later).
Walk-forward: validate 2021, 2022, 2023; each year is scored by models trained only on rows whose labels are fully known before it (21-session purge). Data: bars strictly before 2024-01-01 (the protected holdout is 2025-01-01..2026-11-13);
there is no switch to read it. Raw exchange-feed bars only (the Kite series disagree with it on a quarter of overlapping rows, so the sources are not mixed): the 200-day and 52-week features are therefore empty until about late 2020 and are
handled as missing (LightGBM natively; the others by training-median imputation).
Models (hyperparameters FIXED, none tuned): logistic regression; the existing gradient boosting (scikit-learn HistGradientBoosting, as in the earlier studies); LightGBM (primary candidate). Plus a volatility-only logistic baseline and the six fixed
technical rules B1..B6. Flagging (frozen, all reported, none selected): the top 5%, 10% and 20% of each validation year's eligible rows by score; 10% is the pre-declared primary coverage. Raw scores are NOT probabilities; calibration is reported.
Execution: long at the next open; NON-EXECUTABLE (counted, never repaired) when there is no EQ bar on T+1, the open is missing/invalid, the stock opens at its upper price-band limit, or it is under a GSM stage on T+1 (NSE security list from 2020).
Costs: the repo's DELIVERY schedule per year (positions last 1-20 sessions) plus 0 / 10 / 20 bps slippage per side. Trades leave at the barrier price (or the open that gaps through it), at the close of session 20, or at the adverse barrier when ambiguous.
Statistics: confidence intervals resample blocks of trading days (stocks on one day are dependent); every comparison is registered and counted; a Bonferroni bar is printed.
usage: study_trend_transition.py [--db URL] [--log register.csv] [--preds preds.npz]"""

import argparse
import csv
import hashlib
import json
import math
import os
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from statistics import NormalDist

import lightgbm as lgb
import numpy as np
import pandas as pd
import psycopg
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from study_common import BARS, book_from_db  # noqa: E402,I001

from algo.backtest.costs.calculator import compute_charges
from algo.research import extreme_move as em
from algo.research import next_session_features as ns
from algo.research import trend_transition as tt

END = "2024-01-01"
ROOT = Path(__file__).resolve().parent.parent
SECLIST = ROOT / "data/research/nse_sec_list"
LABEL_VERSION = "TT-L1 (+8% / -4% / 20 sessions, entry next open, ambiguous = non-success)"
VALIDATION_YEARS = (2021, 2022, 2023)
COVERAGES = (0.05, 0.10, 0.20)
PRIMARY_Q = 0.10
SLIPS = (0.0, 0.0010, 0.0020)

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--log", help="write the experiment register to this CSV")
ap.add_argument("--preds", help="save every validation score to this .npz")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")

with psycopg.connect(a.db) as conn:
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, open::float8, high::float8, low::float8, close::float8, volume::float8"
        f" FROM {BARS} WHERE source='kite' AND ts >= '2019-01-01' AND (ts AT TIME ZONE 'Asia/Kolkata')::date < %s ORDER BY instrument_id, ts, dataset_version DESC",
        (END,),
    ).fetchall()
    acts = conn.execute(
        "SELECT instrument_id, ex_date, kind, amount::float8 FROM corporate_action WHERE ex_date >= '2018-10-01' AND ex_date < %s",
        (END,),
    ).fetchall()
    sym = {int(i): s for i, s in conn.execute("SELECT instrument_id, symbol FROM instrument")}
df = pd.DataFrame(rows, columns=["iid", "d", "o", "h", "l", "c", "v"])
del rows
df["d"] = pd.to_datetime(df["d"])
O, H, L, C, V = (  # noqa: E741
    df.pivot(index="d", columns="iid", values=k).sort_index() for k in ("o", "h", "l", "c", "v")
)  # noqa: E741
del df
T, S = C.shape
idx = C.index.values
assert idx.max() < np.datetime64(END)
cols = list(C.columns)
_, bad = ns.corporate_action_masks(idx, cols, acts)
turn = ((C * V).rolling(20, min_periods=15).mean() / 1e7).to_numpy()
universe = (
    (turn >= 5.0) & ~bad & np.isfinite(C.to_numpy()) & (idx >= np.datetime64("2020-01-01"))[:, None]
)
year_of = idx.astype("datetime64[Y]").astype(int) + 1970
first_idx = {y: int(np.searchsorted(idx, np.datetime64(f"{y}-01-01"))) for y in VALIDATION_YEARS}

feat = tt.features(O, H, L, C, V)
rules = tt.baseline_rules(O, H, L, C, V)
elig = {
    "EARLY": tt.early_eligible(H, L, C).to_numpy() & universe,
    "CONFIRMED": tt.confirmed_eligible(H, L, C).to_numpy() & universe,
}
On, Hn, Ln, Cn = O.to_numpy(), H.to_numpy(), L.to_numpy(), C.to_numpy()
ENT = ns.next_open_entry(O, H, L, C, (5, 10, 20))
L60 = L.rolling(60).min().to_numpy()

# ---------------------------------------------------------------- costs and security list
book = book_from_db(a.db if "a" in globals() else None)


def delivery_cost(y: int) -> float:
    sch = book.for_date(date(y, 6, 30), "DELIVERY")
    p, q = Decimal(100), Decimal(1000)
    return float(
        (compute_charges(sch, "BUY", q, p).total + compute_charges(sch, "SELL", q, p).total)
        / (q * p)
    )


COST = {y: delivery_cost(y) for y in range(2020, 2024)}
_sec: dict[str, dict[str, tuple[float, bool]] | None] = {}


def seclist(day: str) -> dict[str, tuple[float, bool]] | None:
    if day not in _sec:
        f = SECLIST / f"sec_list_{day}.csv"
        if not f.exists():
            _sec[day] = None
        else:
            out = {}
            for r in csv.DictReader(f.read_text(errors="replace").splitlines()):
                b = (r.get("Band") or "").strip()
                band = (
                    1000.0
                    if b.lower().startswith("no")
                    else (float(b) if b.replace(".", "", 1).isdigit() else float("nan"))
                )
                out[(r.get("Symbol") or "").strip()] = (
                    band,
                    "GSM" in (r.get("Remarks") or "").upper(),
                )
            _sec[day] = out
    return _sec[day]


def executable(ti: np.ndarray, sj: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(executable?, reason code) for a long at the T+1 open: 0 ok, 1 no EQ bar, 2 bad open, 3 opens at the upper band limit, 4 GSM."""
    i1 = np.minimum(ti + 1, T - 1)
    exists = np.isfinite(Cn[i1, sj]) & np.isfinite(On[i1, sj])
    valid = ENT["valid"][ti, sj]
    band = np.full(len(ti), np.nan)
    gsm = np.zeros(len(ti), dtype=bool)
    for k, (i, j) in enumerate(zip(i1, sj, strict=True)):
        lst = seclist(str(idx[i])[:10])
        if lst is not None:
            hit = lst.get(sym.get(int(cols[j]), ""))
            if hit is not None:
                band[k], gsm[k] = hit
    ent = ENT["entry"][ti, sj]
    at_limit = em.at_upper_limit(ent / Cn[ti, sj] - 1, Cn[ti, sj], band) & valid
    reason = np.zeros(len(ti), dtype=np.int8)
    for mask, code in ((gsm, 4), (at_limit, 3), (~valid, 2), (~exists, 1)):
        reason[mask] = code
    return reason == 0, reason


# ---------------------------------------------------------------- one dataset per strategy
class Data:
    pass


DATA: dict[str, Data] = {}
for strat, mask in elig.items():
    d = Data()
    d.ti, d.sj = np.nonzero(mask)
    lab = tt.barrier_labels(On, Hn, Ln, Cn, d.ti, d.sj)
    keep = lab["code"] != tt.INCOMPLETE
    d.ti, d.sj = d.ti[keep], d.sj[keep]
    d.lab = {k: v[keep] for k, v in lab.items()}
    d.y = (d.lab["code"] == tt.SUCCESS).astype(np.int8)
    d.year = year_of[d.ti]
    d.X = {
        g: np.column_stack(
            [feat[g][nm].to_numpy()[d.ti, d.sj].astype(np.float32) for nm in feat[g]]
        )
        for g in ("E0", "E1")
    }
    d.names = {g: list(feat[g]) for g in ("E0", "E1")}
    for g in d.X:
        d.X[g][~np.isfinite(d.X[g])] = np.nan
    d.exec_ok, d.exec_reason = executable(d.ti, d.sj)
    d.rule = {k: v.to_numpy()[d.ti, d.sj] for k, v in rules.items()}
    d.atr = feat["E1"]["atr"].to_numpy()[d.ti, d.sj]
    d.l60 = L60[d.ti, d.sj]
    d.ct = Cn[d.ti, d.sj]
    DATA[strat] = d
del feat, rules

print(
    f"{S} stocks, {T} sessions to {str(idx[-1])[:10]} (nothing from 2024 on is read); liquid EQ eligible rows (T from 2020): "
    + ", ".join(f"{k} {int(m.sum()):,}" for k, m in elig.items())
)
print(
    "\n=== DATA COVERAGE (E0 / E1 are price and volume only; news, fundamentals, delivery and institutional groups are NOT in this stage)"
)
for strat, d in DATA.items():
    n = len(d.ti)
    print(
        f"{strat}: {n:,} labelled rows from {len(np.unique(d.sj)):,} stocks; outcomes: "
        + ", ".join(
            f"{tt.OUTCOMES[k]} {100 * (d.lab['code'] == k).mean():.1f}%"
            for k in (tt.SUCCESS, tt.FAILED, tt.UNRESOLVED, tt.AMBIGUOUS)
        )
    )
    print(
        "   rows by year: "
        + ", ".join(
            f"{y}: {int((d.year == y).sum()):,} (success rate {100 * d.y[d.year == y].mean():.1f}%)"
            for y in sorted(set(d.year))
            if (d.year == y).any()
        )
    )
    print(
        f"   executable at the next open: {100 * d.exec_ok.mean():.1f}% (no EQ bar {int((d.exec_reason == 1).sum())}, bad open {int((d.exec_reason == 2).sum())}, opens at the upper band limit {int((d.exec_reason == 3).sum())}, GSM {int((d.exec_reason == 4).sum())})"
    )
    for g in ("E0", "E1"):
        miss = np.isnan(d.X[g]).mean(0)
        worst = np.argsort(-miss)[:3]
        print(
            f"   {g}: {d.X[g].shape[1]} features, mean missing {100 * miss.mean():.1f}%; most missing: "
            + ", ".join(f"{d.names[g][k]} {100 * miss[k]:.0f}%" for k in worst)
        )

# ---------------------------------------------------------------- models
LGB_PARAMS = dict(
    n_estimators=300,
    learning_rate=0.05,
    num_leaves=15,
    min_child_samples=100,
    subsample=0.8,
    subsample_freq=1,
    colsample_bytree=0.8,
    reg_lambda=1.0,
    random_state=0,
    n_jobs=3,
    verbose=-1,
)
HGB_PARAMS = dict(
    max_iter=150,
    learning_rate=0.08,
    max_leaf_nodes=31,
    min_samples_leaf=200,
    l2_regularization=1.0,
    early_stopping=False,
    random_state=0,
)


def make(model: str):
    if model == "LR":
        return make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            LogisticRegression(C=1.0, max_iter=300),
        )
    if model == "HGB":
        return HistGradientBoostingClassifier(**HGB_PARAMS)
    return lgb.LGBMClassifier(**LGB_PARAMS)


VOL_COLS = ["atr", "hv20", "hv_rel", "atr_chg10", "range_expansion", "atr_ratio_5_20"]
SCORES: dict[
    tuple[str, str, str], np.ndarray
] = {}  # (strategy, experiment, model) -> score per row (NaN outside validation)
for strat, d in DATA.items():
    n = len(d.ti)
    folds = tt.walk_forward_masks(d.year, d.ti, first_idx)
    for experiment, model in [
        ("E0", "LR"),
        ("E0", "HGB"),
        ("E0", "LGBM"),
        ("E1", "LR"),
        ("E1", "HGB"),
        ("E1", "LGBM"),
        ("VOL", "LR"),
    ]:
        score = np.full(n, np.nan)
        X = (
            d.X["E1"][:, [d.names["E1"].index(c) for c in VOL_COLS]]
            if experiment == "VOL"
            else (d.X["E0"] if experiment == "E0" else np.column_stack([d.X["E0"], d.X["E1"]]))
        )
        for _y, (tr, va) in folds.items():
            tr = tr & (d.lab["code"] != tt.AMBIGUOUS)
            if tr.sum() < 200 or d.y[tr].sum() < 20 or va.sum() == 0:
                continue
            m = make(model).fit(X[tr], d.y[tr])
            score[va] = m.predict_proba(X[va])[:, 1]
        SCORES[(strat, experiment, model)] = score
print(
    f"\nfitted {len(SCORES)} (strategy, experiment, model) combinations over 3 validation years (E0/E1 use identical rows, labels and years; VOL is the volatility-only baseline)"
)

# ---------------------------------------------------------------- evaluation helpers
rngb = np.random.default_rng(1)


def block_ix(nd: int, draws: int = 500, block: int = 10) -> np.ndarray:
    nb = math.ceil(nd / block)
    return ((rngb.integers(0, nd, (draws, nb))[:, :, None] + np.arange(block)) % nd).reshape(
        draws, -1
    )[:, :nd]


def day_sums(d: Data, mask: np.ndarray, value: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return np.bincount(d.ti[mask], weights=value[mask], minlength=T), np.bincount(
        d.ti[mask], minlength=T
    ).astype(float)


def ratio_ci(num: np.ndarray, den: np.ndarray) -> tuple[float, float, float]:
    k = den > 0
    num, den = num[k], den[k]
    if len(den) < 15:
        return float("nan"), float("nan"), float("nan")
    ix = block_ix(len(den))
    r = num[ix].sum(1) / np.maximum(den[ix].sum(1), 1)
    return float(num.sum() / den.sum()), float(np.quantile(r, 0.025)), float(np.quantile(r, 0.975))


def topq_flags(score: np.ndarray, d: Data, q: float | dict[int, float]) -> np.ndarray:
    """Flag the top q share of each validation year's eligible rows by score."""
    f = np.zeros(len(score), dtype=bool)
    for y in VALIDATION_YEARS:
        m = (d.year == y) & np.isfinite(score)
        if m.sum() == 0:
            continue
        qq = q[y] if isinstance(q, dict) else q
        k = int(round(qq * m.sum()))
        if k > 0:
            ii = np.nonzero(m)[0]
            f[ii[np.argsort(-score[ii], kind="stable")[:k]]] = True
    return f


REG: list[dict] = []
TESTS_COUNTED = 0
commit = subprocess.run(
    ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT
).stdout.strip()
dirty = bool(
    subprocess.run(
        ["git", "status", "--porcelain", "src", "scripts"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()
)
feat_hash = hashlib.sha256(Path(tt.__file__).read_text().encode()).hexdigest()[:16]


def dataset_hash(d: Data) -> str:
    h = hashlib.sha256()
    for arr in (d.ti, d.sj, d.lab["code"]):
        h.update(np.ascontiguousarray(arr).tobytes())
    return h.hexdigest()[:16]


def pct(x: float) -> str:
    return "n/a" if not np.isfinite(x) else f"{100 * x:5.1f}%"


# ---------------------------------------------------------------- 1. detection quality
for strat, d in DATA.items():
    va = np.isin(d.year, VALIDATION_YEARS)
    base = d.y[va].mean()
    print(
        f"\n=== 1. DETECTION QUALITY, {strat} (validation 2021-2023 pooled; success base rate {100 * base:.1f}%, {int(va.sum()):,} rows; precision = successes / flagged, ambiguous counted as non-success)"
    )
    print(
        f"{'experiment/model':<14}{'ROC-AUC':>8}{'PR-AUC':>8}   "
        + "".join(
            f"{'top ' + str(int(100 * q)) + '%: prec [CI] lift recall FPR':<46}" for q in COVERAGES
        )
        + "  Brier  logloss"
    )
    for experiment, model in [
        ("VOL", "LR"),
        ("E0", "LR"),
        ("E0", "HGB"),
        ("E0", "LGBM"),
        ("E1", "LR"),
        ("E1", "HGB"),
        ("E1", "LGBM"),
    ]:
        sc = SCORES[(strat, experiment, model)]
        v = va & np.isfinite(sc)
        y, s = d.y[v], sc[v]
        roc, prauc = roc_auc_score(y, s), average_precision_score(y, s)
        cells = []
        for q in COVERAGES:
            f = topq_flags(sc, d, q)
            tp = f & (d.y == 1)
            num, den = day_sums(d, f, (d.y == 1).astype(float))
            p, lo, hi = ratio_ci(num, den)
            rec = tp.sum() / max(d.y[va].sum(), 1)
            fpr = (f & (d.y == 0)).sum() / max((d.y[va] == 0).sum(), 1)
            cells.append(
                f"{pct(p)} [{100 * lo:4.1f},{100 * hi:4.1f}] x{p / base:4.2f} {pct(rec)} {pct(fpr)}   "
            )
            REG.append(
                {
                    "strategy": strat,
                    "experiment": experiment,
                    "model": model,
                    "coverage": q,
                    "precision": p,
                    "p_lo": lo,
                    "p_hi": hi,
                    "lift": p / base,
                    "recall": rec,
                    "fpr": fpr,
                    "roc_auc": roc,
                    "pr_auc": prauc,
                    "n_rows": int(v.sum()),
                    "n_flagged": int(f.sum()),
                    "base_rate": base,
                }
            )
        sc_c = np.clip(s, 1e-6, 1 - 1e-6)
        print(
            f"{experiment + '/' + model:<14}{roc:8.3f}{prauc:8.3f}   "
            + "".join(cells)
            + f"  {brier_score_loss(y, sc_c):.4f}  {log_loss(y, sc_c):.4f}"
        )
    print(
        f"   raw scores are not probabilities; Brier / log loss above are for calibration checking only (a constant forecast at the base rate scores Brier {base * (1 - base):.4f}, log loss {-(base * math.log(base) + (1 - base) * math.log(1 - base)):.4f})"
    )

# ---------------------------------------------------------------- 2. incremental value of E1 over E0 (paired, same rows)
print(
    "\n=== 2. DOES E1 ADD ANYTHING OVER E0? (same rows, same years; difference in precision at the top 10% and in PR-AUC, 95% day-block CI)"
)
for strat, d in DATA.items():
    va = np.isin(d.year, VALIDATION_YEARS)
    for model in ("LR", "HGB", "LGBM"):
        s0, s1 = SCORES[(strat, "E0", model)], SCORES[(strat, "E1", model)]
        f0, f1 = topq_flags(s0, d, PRIMARY_Q), topq_flags(s1, d, PRIMARY_Q)
        n0, m0 = day_sums(d, f0, (d.y == 1).astype(float))
        n1, m1 = day_sums(d, f1, (d.y == 1).astype(float))
        k = (m0 > 0) | (m1 > 0)
        ix = block_ix(int(k.sum()))
        diff = (n1[k][ix].sum(1) / np.maximum(m1[k][ix].sum(1), 1)) - (
            n0[k][ix].sum(1) / np.maximum(m0[k][ix].sum(1), 1)
        )
        pd_ = n1.sum() / m1.sum() - n0.sum() / m0.sum()
        v = va & np.isfinite(s0) & np.isfinite(s1)
        order = np.argsort(d.ti[v], kind="stable")
        ya, a0, a1, di = d.y[v][order], s0[v][order], s1[v][order], d.ti[v][order]
        starts = np.r_[0, np.nonzero(np.diff(di))[0] + 1, len(di)]
        ap_diff = []
        for b in block_ix(len(starts) - 1, draws=150):
            sel = np.concatenate([np.arange(starts[i], starts[i + 1]) for i in b])
            ap_diff.append(
                average_precision_score(ya[sel], a1[sel])
                - average_precision_score(ya[sel], a0[sel])
            )
        apd = average_precision_score(ya, a1) - average_precision_score(ya, a0)
        TESTS_COUNTED += 2
        sd = float(np.std(diff))
        print(
            f"{strat:<10}{model:<5} precision@10%: E1 - E0 = {100 * pd_:+5.2f} pp [{100 * np.quantile(diff, 0.025):+5.2f}, {100 * np.quantile(diff, 0.975):+5.2f}] z {pd_ / sd if sd else float('nan'):+4.1f}   PR-AUC: E1 - E0 = {apd:+.4f} [{np.quantile(ap_diff, 0.025):+.4f}, {np.quantile(ap_diff, 0.975):+.4f}]"
        )

# ---------------------------------------------------------------- 3. fixed technical rules vs the model at the same coverage
print(
    "\n=== 3. FIXED TECHNICAL RULES vs THE MODEL AT THE SAME COVERAGE (each strategy's own eligible rows; precision with ambiguous as non-success)"
)
for strat, d in DATA.items():
    va = np.isin(d.year, VALIDATION_YEARS)
    base = d.y[va].mean()
    print(f"-- {strat}: base success rate {100 * base:.1f}%")
    print(
        f"{'rule':<30}{'flagged':>9}{'coverage':>9}{'rule precision':>16}{'E1-LGBM, same coverage':>24}{'diff (pp, CI)':>24}"
    )
    for name, flag in d.rule.items():
        f = flag & va
        if f.sum() < 30:
            print(f"{name:<30}{int(f.sum()):>9,}{100 * f.sum() / va.sum():8.2f}%  too few flagged")
            continue
        qy = {
            y: float((f & (d.year == y)).sum() / max((d.year == y).sum(), 1))
            for y in VALIDATION_YEARS
        }
        fm = topq_flags(SCORES[(strat, "E1", "LGBM")], d, qy)
        nr_, mr_ = day_sums(d, f, (d.y == 1).astype(float))
        nm_, mm_ = day_sums(d, fm, (d.y == 1).astype(float))
        k = (mr_ > 0) | (mm_ > 0)
        ix = block_ix(int(k.sum()))
        dd = (nm_[k][ix].sum(1) / np.maximum(mm_[k][ix].sum(1), 1)) - (
            nr_[k][ix].sum(1) / np.maximum(mr_[k][ix].sum(1), 1)
        )
        pr, pm = nr_.sum() / mr_.sum(), nm_.sum() / mm_.sum()
        TESTS_COUNTED += 1
        print(
            f"{name:<30}{int(f.sum()):>9,}{100 * f.sum() / va.sum():8.2f}%{pct(pr):>16}{pct(pm):>24}{100 * (pm - pr):+8.2f} [{100 * np.quantile(dd, 0.025):+5.2f},{100 * np.quantile(dd, 0.975):+5.2f}]"
        )

# ---------------------------------------------------------------- 4. volatility stratification
print(
    "\n=== 4. VOLATILITY CHECK: success rate by ATR% tercile (terciles fixed on rows before 2021), for all rows, the top 10% of E1-LGBM, and the top 10% of the volatility-only baseline"
)
for strat, d in DATA.items():
    tr_atr = d.atr[(d.year < 2021) & np.isfinite(d.atr)]
    cuts = (
        np.quantile(tr_atr, [1 / 3, 2 / 3])
        if len(tr_atr) > 50
        else np.quantile(d.atr[np.isfinite(d.atr)], [1 / 3, 2 / 3])
    )
    terc = np.digitize(d.atr, cuts)
    va = np.isin(d.year, VALIDATION_YEARS)
    f1, fv = (
        topq_flags(SCORES[(strat, "E1", "LGBM")], d, PRIMARY_Q),
        topq_flags(SCORES[(strat, "VOL", "LR")], d, PRIMARY_Q),
    )
    print(f"-- {strat}")
    for t_, nm in enumerate(("low vol", "mid vol", "high vol")):
        m = va & (terc == t_)
        a_ = d.y[m].mean()
        b_ = d.y[m & f1].mean() if (m & f1).sum() else float("nan")
        c_ = d.y[m & fv].mean() if (m & fv).sum() else float("nan")
        print(
            f"   {nm:<8} rows {int(m.sum()):>6,}: all rows {pct(a_)} | E1-LGBM top 10% {pct(b_)} (n={int((m & f1).sum())}, x{b_ / a_ if a_ else float('nan'):.2f}) | volatility-only top 10% {pct(c_)} (n={int((m & fv).sum())}, x{c_ / a_ if a_ else float('nan'):.2f})"
        )

# ---------------------------------------------------------------- 5. how early
print(
    "\n=== 5. HOW EARLY: successes (E1-LGBM top 10% vs all): sessions from the entry to the +8% target, and how far from the 60-session low to the target price the stock had already travelled at the signal close"
)
for strat, d in DATA.items():
    f = topq_flags(SCORES[(strat, "E1", "LGBM")], d, PRIMARY_Q) & (d.y == 1)
    target = d.lab["entry"] * 1.08
    travelled = (d.ct - d.l60) / (target - d.l60)
    allsucc = np.isin(d.year, VALIDATION_YEARS) & (d.y == 1)
    for lab_, m in (("flagged successes", f), ("all successes", allsucc)):
        if m.sum() < 10:
            continue
        k, tv = d.lab["k"][m], travelled[m]
        print(
            f"{strat:<10}{lab_:<18} n={int(m.sum()):>5,}  sessions to target: median {np.median(k):.0f} (quartiles {np.quantile(k, 0.25):.0f}-{np.quantile(k, 0.75):.0f});  already travelled at signal: median {100 * np.nanmedian(tv):.0f}% (quartiles {100 * np.nanquantile(tv, 0.25):.0f}-{100 * np.nanquantile(tv, 0.75):.0f}%); signal within 10% of the 60-session low: {100 * np.nanmean(d.ct[m] <= 1.10 * d.l60[m]):.0f}%"
        )

# ---------------------------------------------------------------- 6. next-open trading
print(
    "\n=== 6. NEXT-OPEN TRADING of the flagged rows (executable only; delivery costs from the repo schedule + slippage per side; exit at the barrier / open that gaps through it / close of session 20 / adverse barrier if ambiguous)"
)
for strat, d in DATA.items():
    print(f"-- {strat}")
    cost_all = np.array([COST.get(int(y), COST[2023]) for y in d.year])
    for experiment, model in (("E1", "LGBM"), ("E0", "LGBM"), ("E1", "LR")):
        sc = SCORES[(strat, experiment, model)]
        for q in COVERAGES:
            f = topq_flags(sc, d, q)
            ex = f & d.exec_ok
            if ex.sum() < 30:
                continue
            g = d.lab["exit_ret"][ex]
            outs = []
            for sl in SLIPS:
                net = d.lab["exit_ret"] - cost_all - 2 * sl
                m, lo, hi = ratio_ci(*day_sums(d, ex, net))
                nn = net[ex]
                w, l_ = nn[nn > 0], nn[nn <= 0]
                outs.append(
                    f"{int(1e4 * sl)}bps net {100 * m:+.2f}% [{100 * lo:+.2f},{100 * hi:+.2f}] win {100 * (nn > 0).mean():.0f}% PF {w.sum() / -l_.sum() if l_.sum() < 0 else float('nan'):.2f}"
                )
            fw = {h: ENT[f"ret{h}"][d.ti[ex], d.sj[ex]] for h in (5, 10, 20)}
            print(
                f"  {experiment}/{model} top {int(100 * q):>2}%: trades {int(ex.sum()):>5,} ({int(f.sum() - ex.sum())} of {int(f.sum()):,} flagged not executable)  gross {100 * g.mean():+.2f}%  | "
                + " | ".join(outs)
                + f"  | forward T+5/10/20 close vs entry open {100 * np.nanmean(fw[5]):+.1f}/{100 * np.nanmean(fw[10]):+.1f}/{100 * np.nanmean(fw[20]):+.1f}%  best/worst {100 * d.lab['best'][ex].mean():+.1f}/{100 * d.lab['worst'][ex].mean():+.1f}%"
            )
            if experiment == "E1" and model == "LGBM" and q == PRIMARY_Q:
                ti_, sj_, k_ = d.ti[ex], d.sj[ex], d.lab["k"][ex].astype(int)
                ent = d.lab["entry"][ex]
                exit_price = ent * (1 + d.lab["exit_ret"][ex])
                dsum, dcnt = np.zeros(T + 25), np.zeros(T + 25)
                cst = cost_all[ex] / 2 + SLIPS[1]
                for s in range(1, 21):
                    live = k_ >= s
                    prev = ent if s == 1 else Cn[np.minimum(ti_ + s - 1, T - 1), sj_]
                    px = np.where(k_ == s, exit_price, Cn[np.minimum(ti_ + s, T - 1), sj_])
                    r = px / prev - 1 - (cst if s == 1 else 0.0) - np.where(k_ == s, cst, 0.0)
                    np.add.at(dsum, (ti_ + s)[live], r[live])
                    np.add.at(dcnt, (ti_ + s)[live], 1)
                vd = np.arange(first_idx[2021], T)
                ser = np.where(dcnt[vd] > 0, dsum[vd] / np.maximum(dcnt[vd], 1), 0.0)
                eq = np.cumprod(1 + ser)
                dd = float((eq / np.maximum.accumulate(eq) - 1).min())
                sh = (
                    float(ser.mean() / ser.std() * math.sqrt(252))
                    if ser.std() > 0
                    else float("nan")
                )
                print(
                    f"      portfolio (equal weight over open positions, 10 bps): positions open on {int((dcnt[vd] > 0).sum())} of {len(vd)} days (mean {dcnt[vd][dcnt[vd] > 0].mean():.1f}, max {int(dcnt[vd].max())}); Sharpe {sh:+.2f}; max drawdown {100 * dd:.1f}%; round trips per day {int(ex.sum()) / len(vd):.2f}"
                )
    allv = np.isin(d.year, VALIDATION_YEARS) & d.exec_ok
    print(
        f"  all executable eligible rows (no model): n {int(allv.sum()):,}, gross {100 * d.lab['exit_ret'][allv].mean():+.2f}%, net at 10 bps {100 * (d.lab['exit_ret'][allv] - cost_all[allv] - 0.002).mean():+.2f}%"
    )

# ---------------------------------------------------------------- 7. year by year
print(
    "\n=== 7. YEAR BY YEAR, E1-LGBM top 10% (precision vs the year's base rate; executable net at 10 bps per trade)"
)
for strat, d in DATA.items():
    f = topq_flags(SCORES[(strat, "E1", "LGBM")], d, PRIMARY_Q)
    cost_all = np.array([COST.get(int(y), COST[2023]) for y in d.year])
    cells = []
    for y in VALIDATION_YEARS:
        m = (d.year == y) & f
        ex = m & d.exec_ok
        net = (d.lab["exit_ret"] - cost_all - 0.002)[ex]
        cells.append(
            f"{y}: prec {pct(d.y[m].mean() if m.sum() else float('nan'))} vs base {pct(d.y[d.year == y].mean())} (n={int(m.sum())}), net {100 * np.nanmean(net) if len(net) else float('nan'):+.2f}%"
        )
    print(f"{strat:<10}" + " | ".join(cells))

# ---------------------------------------------------------------- register
zc = NormalDist().inv_cdf(1 - 0.05 / 2 / max(TESTS_COUNTED, 1))
print(
    f"\n=== 8. STATISTICAL CONTROL: {TESTS_COUNTED} registered paired comparisons (E1 vs E0 on two metrics, and the model vs each fixed rule); Bonferroni |z| >= {zc:.2f}; every interval above is a 95% day-block interval"
)
ds = {k: dataset_hash(v) for k, v in DATA.items()}
print(
    f"code commit {commit[:10]}{' + uncommitted changes' if dirty else ''}; label version: {LABEL_VERSION}; feature module hash {feat_hash}; dataset hashes "
    + ", ".join(f"{k} {v}" for k, v in ds.items())
)
for r in REG:
    r.update(
        {
            "experiment_id": f"TT-{r['strategy']}-{r['experiment']}-{r['model']}-q{int(100 * r['coverage'])}",
            "label_version": LABEL_VERSION,
            "feature_hash": feat_hash,
            "dataset_hash": ds[r["strategy"]],
            "code_commit": commit + ("+dirty" if dirty else ""),
            "lgbm_params": json.dumps(LGB_PARAMS) if r["model"] == "LGBM" else "",
            "validation_years": "2021,2022,2023",
            "prediction_timestamp": "after close of T",
            "entry": "T+1 open",
        }
    )
if a.log:
    pd.DataFrame(REG).to_csv(a.log, index=False)
    print(f"experiment register: {len(REG)} rows -> {a.log}")
if a.preds:
    np.savez_compressed(
        a.preds,
        **{f"{k[0]}__{k[1]}__{k[2]}": v for k, v in SCORES.items()},
        **{f"{s}__ti": DATA[s].ti for s in DATA},
        **{f"{s}__sj": DATA[s].sj for s in DATA},
        **{f"{s}__code": DATA[s].lab["code"] for s in DATA},
    )
    print(
        f"validation scores saved to {a.preds} (sha256 {hashlib.sha256(Path(a.preds).read_bytes()).hexdigest()[:16]})"
    )
