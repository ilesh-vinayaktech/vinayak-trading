# ruff: noqa: E501
"""Early-large-upside research V2: feature-group ablation WITH and WITHOUT volatility, on the V1 split, development period only.

Question (owner): do the new feature groups find big upward moves better than V1, and is any of that skill just volatility?
Data: Kite adjusted bars to `development_end` of config/research_holdout.json (2025-01-01 onward is never read). Universe as V1 (20-day average traded value >= Rs 5 crore).
Split as V1: train to 2022-11-30, selection 2023-01-02..2023-11-30 (trees/config chosen here only), out-of-time 2024-01-02..2024-12-31; the gaps are >= 20 sessions (asserted).
Targets: A (V1: close +10% 10 sessions later), B10 (next open to the horizon close >= +10%), C (first passage: +10% before -5% from the next open).
Feature sets: V1 (24), V1+price, V1+volume, V1+early, V1+volatility, V1+price+volume+early, ALL, each ON (as defined) and OFF (every feature marked `volatility` removed,
including V1's vol60 / bwr / rng15); VOL_ONLY (only the volatility features) is the baseline any set must beat to claim more than volatility.
Judged on 2024 (out-of-time): AUC, PR-AUC, precision at the top 1/2/5/10% of all scores, lift against the SAME day's base rate, the EARLY segment (prior 5-session return < 3%) on its own,
and for target C the barrier-trade expectancy of the top 5% of each day after the repo's real cost. Date-block bootstrap (15-day blocks, 1000 draws) for the key rows.
usage: study_winner_v2.py [--db URL] [--out DIR] [--min-turnover-cr 5] [--families]   (--families also compares model types on the best set)"""

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from study_common import flat_cost
from winner_v2_common import DEV_END, TE0, TR_END, VA0, VA1, load

from algo.research import winner_features as wf

ROOT = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--out", default=str(ROOT / "data/research/winner_v2"))
ap.add_argument("--min-turnover-cr", type=float, default=5.0)
ap.add_argument("--families", action="store_true")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
OUT = Path(a.out)
OUT.mkdir(parents=True, exist_ok=True)
SEED = 0
T0 = time.time()
D = load(a.db, a.min_turnover_cr)
day_of, dts, Y, EXR, EARLY, tr, va, te, names, col, X = (
    D.day_of,
    D.dts,
    D.Y,
    D.EXR,
    D.EARLY,
    D.tr,
    D.va,
    D.te,
    D.names,
    D.col,
    D.X,
)
N = D.n

V1 = [n for n in names if wf.META[n].group == "v1"]
GRP = {g: [n for n in names if wf.META[n].group == g] for g in wf.GROUPS}
SETS = {
    "V1": V1,
    "V1+price": V1 + GRP["price"],
    "V1+volume": V1 + GRP["volume"],
    "V1+early": V1 + GRP["early"],
    "V1+volatility": V1 + GRP["volatility"],
    "V1+price+volume+early": V1 + GRP["price"] + GRP["volume"] + GRP["early"],
    "ALL": V1 + GRP["price"] + GRP["volume"] + GRP["early"] + GRP["volatility"],
}
VOLF = [n for n in names if wf.META[n].volatility]
EXPS: list[tuple[str, str, list[str]]] = []  # (set name, vol mode, columns)
seen: set[frozenset[str]] = set()
for nm, cols in SETS.items():
    for mode, cc in (("ON", cols), ("OFF", [c for c in cols if not wf.META[c].volatility])):
        if frozenset(cc) not in seen:
            seen.add(frozenset(cc))
            EXPS.append((nm, mode, cc))
EXPS.append(("VOL_ONLY", "ON", VOLF))

# ---------------------------------------------------------------- scoring helpers
DAY_BASE = {k: pd.Series(Y[k]).groupby(day_of).transform("mean").to_numpy() for k in Y}


def pr_at(y: np.ndarray, p: np.ndarray, base: np.ndarray, top: float) -> tuple[float, float]:
    mk = p >= np.quantile(p, 1 - top / 100)
    hit, exp = float(y[mk].sum()), float(base[mk].sum())
    return 100 * hit / mk.sum(), hit / max(exp, 1e-12)


def metrics(k: str, p: np.ndarray, sel: np.ndarray) -> dict[str, float]:
    y, b = Y[k][sel], DAY_BASE[k][sel]
    out = {
        "auc": roc_auc_score(y, p),
        "prauc": average_precision_score(y, p),
        "base": 100 * y.mean(),
    }
    for t in (1, 2, 5, 10):
        out[f"p{t}"], out[f"l{t}"] = pr_at(y, p, b, t)
    e = EARLY[sel]
    out["early_l5"] = pr_at(y[e], p[e], b[e], 5)[1] if e.sum() > 1000 else float("nan")
    return out


CONFIGS = [{"max_depth": 3, "num_leaves": 7}, {"max_depth": 5, "num_leaves": 15}]
COST = flat_cost()


def fit_lgb(
    Xtr: np.ndarray, ytr: np.ndarray, Xva: np.ndarray, yva: np.ndarray
) -> tuple[lgb.LGBMClassifier, int, dict[str, Any]]:
    """Fit each predefined config once; pick (config, trees in 100/200/300) by 2023 AUC only."""
    best: tuple[float, lgb.LGBMClassifier, int, dict[str, Any]] | None = None
    for cfg in CONFIGS:
        mdl = lgb.LGBMClassifier(
            n_estimators=300,
            learning_rate=0.05,
            min_child_samples=300,
            subsample=0.8,
            subsample_freq=1,
            colsample_bytree=0.8,
            random_state=SEED,
            n_jobs=4,
            verbose=-1,
            deterministic=True,
            force_row_wise=True,
            **cfg,
        )
        mdl.fit(Xtr, ytr)
        for k in (100, 200, 300):
            au = roc_auc_score(yva, mdl.predict_proba(Xva, num_iteration=k)[:, 1])
            if best is None or au > best[0]:
                best = (au, mdl, k, {**cfg, "trees": k, "auc_2023": round(au, 4)})
    assert best is not None
    return best[1], best[2], best[3]


def git_state() -> tuple[str, str]:
    h = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "src", "scripts"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()
    return h, "dirty" if dirty else "clean"


COMMIT, TREE = git_state()
DATASET_HASH = hashlib.sha256(
    f"{N}|{dts.min()}|{dts.max()}|{int(Y['A'].sum())}|{int(Y['C'].sum())}|{','.join(names)}".encode()
).hexdigest()[:16]
REG: list[dict[str, object]] = []
RES: dict[tuple[str, str, str], dict[str, float]] = {}
SCORES: dict[tuple[str, str, str], np.ndarray] = {}
SEL_AUC: dict[tuple[str, str, str], float] = {}

print(
    f"\ncommit {COMMIT[:10]} ({TREE} tree), dataset {DATASET_HASH}; cost model: repo DB schedules, round trip {100 * COST:.2f}%\n"
)
for target in ("A", "B10", "C"):
    print(
        f"=== target {target}: out-of-time 2024 (selection 2023 chose trees/config). base rate {100 * Y[target][te].mean():.2f}% (2023 {100 * Y[target][va].mean():.2f}%)"
    )
    print(
        f"{'set':<24}{'vol':>4}{'nfeat':>6}{'trees':>6}{'AUC23':>7}{'AUC24':>7}{'PR-AUC':>7}{'P@1':>6}{'P@2':>6}{'P@5':>6}{'P@10':>6}{'lift@5':>7}{'lift@10':>8}{'EARLY l@5':>10}"
    )
    for nm, mode, cc in EXPS:
        ji = [col[c] for c in cc]
        mdl, ktrees, info = fit_lgb(X[tr][:, ji], Y[target][tr], X[va][:, ji], Y[target][va])
        p = mdl.predict_proba(X[te][:, ji], num_iteration=ktrees)[:, 1]
        r = metrics(target, p, te)
        RES[(target, nm, mode)], SCORES[(target, nm, mode)], SEL_AUC[(target, nm, mode)] = (
            r,
            p,
            info["auc_2023"],
        )
        print(
            f"{nm:<24}{mode:>4}{len(cc):>6}{ktrees:>6}{info['auc_2023']:>7.3f}{r['auc']:>7.3f}{r['prauc']:>7.3f}{r['p1']:>6.1f}{r['p2']:>6.1f}{r['p5']:>6.1f}{r['p10']:>6.1f}{r['l5']:>7.2f}{r['l10']:>8.2f}{r['early_l5']:>10.2f}"
        )
        REG.append(
            {
                "experiment_id": f"WINNER_V2_{target}_{nm.replace('+', '_')}_{mode}",
                "git_commit": COMMIT,
                "working_tree": TREE,
                "dataset_hash": DATASET_HASH,
                "label_version": "winner_labels.v1",
                "universe": f"liquid>={a.min_turnover_cr}cr kite-adjusted dev<={DEV_END}",
                "train": f"..{TR_END.date()}",
                "selection": f"{VA0.date()}..{VA1.date()}",
                "evaluation": f"{TE0.date()}..{DEV_END}",
                "model": "lightgbm",
                "params": json.dumps(info),
                "seed": SEED,
                "n_features": len(cc),
                **{k: round(v, 4) for k, v in r.items()},
            }
        )
    print()

# ---------------------------------------------------------------- with vs without volatility: the differences that answer the question
print(
    "=== WITH minus WITHOUT volatility, per feature set (2024, lightgbm). positive = the volatility features helped"
)
print(f"{'target':<7}{'set':<24}{'dAUC':>8}{'dPR-AUC':>9}{'dlift@5':>9}{'dlift@10':>9}")
for target in ("A", "B10", "C"):
    for nm in SETS:
        on, off = RES.get((target, nm, "ON")), RES.get((target, nm, "OFF"))
        if on and off:
            print(
                f"{target:<7}{nm:<24}{on['auc'] - off['auc']:>+8.4f}{on['prauc'] - off['prauc']:>+9.4f}{on['l5'] - off['l5']:>+9.2f}{on['l10'] - off['l10']:>+9.2f}"
            )
print()


# ---------------------------------------------------------------- reliability: per-day top 5%, 15-day block bootstrap over dates
def per_day_top(
    p: np.ndarray, k: str, frac: float = 0.05
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    df = pd.DataFrame({"d": day_of[te], "p": p, "y": Y[k][te], "b": DAY_BASE[k][te], "x": EXR[te]})
    df["top"] = df.groupby("d")["p"].rank(pct=True) > 1 - frac
    g = df[df["top"]].groupby("d")
    hits = g["y"].sum()
    return (
        hits.to_numpy(),
        g["b"].sum().to_numpy(),
        g["x"].mean().to_numpy(),
        df.groupby("d")["x"].mean().reindex(hits.index).to_numpy(),
    )


def boot(
    num: np.ndarray, den: np.ndarray, block: int = 15, reps: int = 1000, ratio: bool = True
) -> tuple[float, float, float]:
    n = len(num)
    rng = np.random.default_rng(SEED)
    starts = rng.integers(0, n, (reps, -(-n // block)))
    ii = ((starts[:, :, None] + np.arange(block)) % n).reshape(reps, -1)[:, :n]
    est = num[ii].sum(1) / den[ii].sum(1) if ratio else num[ii].mean(1)
    pt = num.sum() / den.sum() if ratio else num.mean()
    return float(pt), float(np.percentile(est, 2.5)), float(np.percentile(est, 97.5))


print(
    "=== reliability, 2024: top 5% of each day. lift = hits / same-day expected hits (1.0 = chance); 95% CI from a 15-day moving-block bootstrap over dates (1000 draws)"
)
print(
    f"{'target':<7}{'experiment':<30}{'lift@5 [95% CI]':>26}   net barrier-trade exit return (+10%/-5%), top 5% minus all stocks that day, after cost [95% CI]"
)
for target in ("A", "C"):
    for nm, mode in (
        ("V1", "ON"),
        ("V1", "OFF"),
        ("ALL", "ON"),
        ("ALL", "OFF"),
        ("VOL_ONLY", "ON"),
    ):
        if (target, nm, mode) not in SCORES:
            continue
        hits, exp, xr, xr_all = per_day_top(SCORES[(target, nm, mode)], target)
        lf = boot(hits, exp)
        ok = np.isfinite(xr) & np.isfinite(xr_all)
        ex = boot(xr[ok] - xr_all[ok] - COST, np.ones(ok.sum()), ratio=False)
        print(
            f"{target:<7}{nm + ' ' + mode:<30}{lf[0]:>8.2f} [{lf[1]:.2f}, {lf[2]:.2f}]   {100 * ex[0]:>+8.2f}% [{100 * ex[1]:+.2f}%, {100 * ex[2]:+.2f}%]"
        )
print("(ambiguous candles are excluded from the barrier-trade column)\n")

# ---------------------------------------------------------------- model families on the set chosen by 2023 selection (target A)
if a.families:
    cand = [(nm, mode) for nm, mode, _ in EXPS if nm != "VOL_ONLY"]
    best_nm, best_mode = max(cand, key=lambda t: SEL_AUC[("A", *t)])
    print(
        f"=== model families on {best_nm} ({best_mode} volatility), chosen by 2023 AUC only; target A, 2024"
    )
    cc = next(c for nm, mode, c in EXPS if (nm, mode) == (best_nm, best_mode))
    ji = [col[c] for c in cc]
    Xtr, Xva, Xte = X[tr][:, ji], X[va][:, ji], X[te][:, ji]
    ytr, yva = Y["A"][tr], Y["A"][va]
    fam: dict[str, np.ndarray] = {}

    def pick(make: Any) -> np.ndarray:
        best_au, best_p = -1.0, np.empty(0)
        for it in (100, 200, 300):
            mdl = make(it).fit(Xtr, ytr)
            au = roc_auc_score(yva, mdl.predict_proba(Xva)[:, 1])
            if au > best_au:
                best_au, best_p = au, mdl.predict_proba(Xte)[:, 1]
        return best_p

    fam["sklearn HistGradientBoosting (V1's)"] = pick(
        lambda it: HistGradientBoostingClassifier(
            max_depth=4, learning_rate=0.05, max_iter=it, early_stopping=False, random_state=SEED
        )
    )
    fam["XGBoost"] = pick(
        lambda it: xgb.XGBClassifier(
            n_estimators=it,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=100,
            tree_method="hist",
            n_jobs=4,
            random_state=SEED,
            verbosity=0,
        )
    )
    mdl_l, k_l, _ = fit_lgb(Xtr, ytr, Xva, yva)
    fam["LightGBM"] = mdl_l.predict_proba(Xte, num_iteration=k_l)[:, 1]
    fam["Logistic regression"] = (
        make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            LogisticRegression(C=0.1, max_iter=300),
        )
        .fit(Xtr, ytr)
        .predict_proba(Xte)[:, 1]
    )
    fam["Random forest"] = (
        make_pipeline(
            SimpleImputer(strategy="median"),
            RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                min_samples_leaf=300,
                max_samples=0.3,
                n_jobs=4,
                random_state=SEED,
            ),
        )
        .fit(Xtr, ytr)
        .predict_proba(Xte)[:, 1]
    )
    print(f"{'model':<38}{'AUC24':>7}{'PR-AUC':>8}{'P@5':>6}{'lift@5':>8}{'lift@10':>9}")
    for nm_, p in fam.items():
        r = metrics("A", p, te)
        print(
            f"{nm_:<38}{r['auc']:>7.3f}{r['prauc']:>8.3f}{r['p5']:>6.1f}{r['l5']:>8.2f}{r['l10']:>9.2f}"
        )
        REG.append(
            {
                "experiment_id": f"WINNER_V2_A_FAMILY_{nm_.split()[0].upper()}",
                "git_commit": COMMIT,
                "working_tree": TREE,
                "dataset_hash": DATASET_HASH,
                "model": nm_,
                "seed": SEED,
                **{k: round(v, 4) for k, v in r.items()},
            }
        )

keys = sorted({k for r_ in REG for k in r_})
with open(OUT / "register.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=keys)
    w.writeheader()
    w.writerows(REG)
print(
    f"\nexperiment register: {len(REG)} rows -> {OUT / 'register.csv'}; total {time.time() - T0:.0f}s"
)
