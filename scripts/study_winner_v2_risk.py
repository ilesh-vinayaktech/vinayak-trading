# ruff: noqa: E501
"""Early-large-upside research V2, risk-adjusted targets: train on what a trade EARNS, not on whether the stock eventually rose.

Why: in study_winner_v2.py the top 5% of each day by "will it rise 10%" returned 0.4-0.5% LESS than the average stock on the +10% / -5% barrier trade after cost: the model buys volatile
stocks, which win more often but hit the stop more. Targets here, all measured from the next open with the barrier trade (+10% target, -5% stop, 10 sessions, gap exits at the open):
  SvF     classifier: success vs failure among the trades that resolved (NO_EVENT and ambiguous rows are not in its training set); score = P(success | resolved)
  EXR     regressor: the barrier trade's exit return (gross)
  PROFIT  classifier: the trade's exit return beats the repo's real round-trip cost
  A, C    the earlier classifiers (rise 10%; success before failure over ALL rows), for comparison
Feature sets, each ON (as defined) and OFF (every `volatility` feature removed): V1, V1+price+volume+early, ALL; and VOL_ONLY.
Judged on 2024 (out-of-time; trees/config chosen on 2023 only; 2025-01-01 onward never read): the top 5% / 10% of each day: barrier-trade return after cost, against (1) the average stock that day and
(2) the average stock of the SAME day AND the same volatility quintile (so a model that only picks volatile stocks gets no credit), 95% CI by a 15-day moving-block bootstrap over dates; and the daily rank IC of the score
against the trade's exit return.
usage: study_winner_v2_risk.py [--db URL] [--out DIR] [--min-turnover-cr 5]"""

import argparse
import csv
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
from sklearn.metrics import roc_auc_score
from study_common import flat_cost
from winner_v2_common import DEV_END, ROOT, load

from algo.research import winner_features as wf
from algo.research import winner_labels as wl

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--out", default=str(ROOT / "data/research/winner_v2"))
ap.add_argument("--min-turnover-cr", type=float, default=5.0)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
OUT = Path(a.out)
OUT.mkdir(parents=True, exist_ok=True)
SEED, T0 = 0, time.time()
D = load(a.db, a.min_turnover_cr)
day_of, Y, OUTC, EXR, tr, va, te, names, col, X = (
    D.day_of,
    D.Y,
    D.OUT,
    D.EXR,
    D.tr,
    D.va,
    D.te,
    D.names,
    D.col,
    D.X,
)
COST = flat_cost()
V1 = [n for n in names if wf.META[n].group == "v1"]
GRP = {g: [n for n in names if wf.META[n].group == g] for g in wf.GROUPS}
SETS = {
    "V1": V1,
    "V1+price+volume+early": V1 + GRP["price"] + GRP["volume"] + GRP["early"],
    "ALL": V1 + GRP["price"] + GRP["volume"] + GRP["early"] + GRP["volatility"],
}
EXPS: list[tuple[str, str, list[str]]] = []
seen: set[frozenset[str]] = set()
for nm, cols in SETS.items():
    for mode, cc in (("ON", cols), ("OFF", [c for c in cols if not wf.META[c].volatility])):
        if frozenset(cc) not in seen:
            seen.add(frozenset(cc))
            EXPS.append((nm, mode, cc))
EXPS.append(("VOL_ONLY", "ON", [n for n in names if wf.META[n].volatility]))
CONFIGS = [{"max_depth": 3, "num_leaves": 7}, {"max_depth": 5, "num_leaves": 15}]
PARAMS: dict[str, Any] = {
    "n_estimators": 300,
    "learning_rate": 0.05,
    "min_child_samples": 300,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "random_state": SEED,
    "n_jobs": 4,
    "verbose": -1,
    "deterministic": True,
    "force_row_wise": True,
}

# ---------------------------------------------------------------- helpers
fin = np.isfinite(EXR)
vol20 = X[
    :, col["volatility_20d"]
]  # used to MATCH stocks by volatility when judging; a model sees it only if its feature set contains it
RESOLVED = np.isin(OUTC, (wl.SUCCESS, wl.FAILURE))


def daily_ic(days: np.ndarray, s: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Spearman rank correlation of score and outcome within each day (vector form)."""
    df = pd.DataFrame({"d": days, "s": s, "y": y})
    a_ = df.groupby("d")["s"].rank(pct=True)
    b_ = df.groupby("d")["y"].rank(pct=True)
    a_, b_ = a_ - a_.groupby(df["d"]).transform("mean"), b_ - b_.groupby(df["d"]).transform("mean")
    num = (a_ * b_).groupby(df["d"]).sum()
    den = np.sqrt((a_**2).groupby(df["d"]).sum() * (b_**2).groupby(df["d"]).sum())
    return (num / den).to_numpy()


def fit_select(
    kind: str, ytr: np.ndarray, rtr: np.ndarray, ji: list[int]
) -> tuple[Any, int, dict[str, Any]]:
    """Fit each config once on the training rows `rtr`; pick (config, trees in 100/200/300) by the 2023 score only (AUC for a classifier, mean daily rank IC with the trade return for a regressor)."""
    best: tuple[float, Any, int, dict[str, Any]] | None = None
    vtarget = {
        "A": Y["A"],
        "C": Y["C"],
        "SvF": (OUTC == wl.SUCCESS).astype(int),
        "PROFIT": (EXR - COST > 0).astype(int),
    }
    vsel = {"A": va, "C": va, "SvF": va & RESOLVED, "PROFIT": va & fin, "reg": va & fin}[kind]
    for cfg in CONFIGS:
        mdl = (lgb.LGBMRegressor if kind == "reg" else lgb.LGBMClassifier)(**PARAMS, **cfg).fit(
            X[rtr][:, ji], ytr
        )
        for k in (100, 200, 300):
            if kind == "reg":
                sc = float(
                    np.nanmean(
                        daily_ic(
                            day_of[vsel], mdl.predict(X[vsel][:, ji], num_iteration=k), EXR[vsel]
                        )
                    )
                )
            else:
                sc = roc_auc_score(
                    vtarget[kind][vsel], mdl.predict_proba(X[vsel][:, ji], num_iteration=k)[:, 1]
                )
            if best is None or sc > best[0]:
                best = (sc, mdl, k, {**cfg, "trees": k, "sel_2023": round(sc, 4)})
    assert best is not None
    return best[1], best[2], best[3]


def boot_mean(x: np.ndarray, block: int = 15, reps: int = 1000) -> tuple[float, float, float]:
    n = len(x)
    rng = np.random.default_rng(SEED)
    starts = rng.integers(0, n, (reps, -(-n // block)))
    ii = ((starts[:, :, None] + np.arange(block)) % n).reshape(reps, -1)[:, :n]
    est = x[ii].mean(1)
    return float(x.mean()), float(np.percentile(est, 2.5)), float(np.percentile(est, 97.5))


def score_trades(score: np.ndarray) -> dict[Any, Any]:
    """Out-of-time 2024: the top 5% / 10% of each day, by the barrier trade (rows with an ordered outcome)."""
    sel = te & fin
    df = pd.DataFrame(
        {"d": day_of[sel], "s": score, "x": EXR[sel], "v": vol20[sel], "o": OUTC[sel]}
    )
    df["rk"] = df.groupby("d")["s"].rank(pct=True)
    df["vq"] = (
        (df.groupby("d")["v"].rank(pct=True) * 5).clip(upper=4.999).fillna(-1).astype(int)
    )  # rows with no volatility yet form their own bucket
    df["xu"] = df.groupby("d")["x"].transform("mean")
    df["xm"] = df.groupby(["d", "vq"])["x"].transform("mean")
    out: dict[Any, Any] = {
        "ic": float(
            np.nanmean(daily_ic(df["d"].to_numpy(), df["s"].to_numpy(), df["x"].to_numpy()))
        )
    }
    for top in (5, 10):
        s = df[df["rk"] > 1 - top / 100]
        g = s.groupby("d")
        out[top] = {
            "n": len(s) / g.ngroups,
            "succ": 100 * (s["o"] == wl.SUCCESS).mean(),
            "fail": 100 * (s["o"] == wl.FAILURE).mean(),
            "net": boot_mean((g["x"].mean() - COST).to_numpy()),
            "vs_all": boot_mean((g["x"].mean() - g["xu"].mean()).to_numpy()),
            "vs_vm": boot_mean((g["x"].mean() - g["xm"].mean()).to_numpy()),
        }
    return out


def git_state() -> tuple[str, str]:
    h = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "src", "scripts"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()
    return h, "dirty" if dirty else "clean"


COMMIT, TREE = git_state()
REG: list[dict[str, object]] = []
print(
    f"\ncommit {COMMIT[:10]} ({TREE} tree); real round-trip cost {100 * COST:.2f}%; barrier trade +10% / -5% from the next open, 10 sessions"
)
base = EXR[te & fin]
print(
    f"all stocks 2024 (the trade without any selection): gross {100 * base.mean():+.2f}%, net {100 * (base.mean() - COST):+.2f}%; success {100 * (OUTC[te & fin] == wl.SUCCESS).mean():.1f}%, failure {100 * (OUTC[te & fin] == wl.FAILURE).mean():.1f}%\n"
)


def row(label: str, mode: str, nf: int, info: dict[str, Any], r: dict[Any, Any]) -> None:
    for top in (5, 10):
        t = r[top]
        print(
            f"{label:<22}{mode:>4}{nf:>4} {top:>3}% {t['n']:>5.0f} {t['succ']:>6.1f} {t['fail']:>6.1f} | {100 * t['net'][0]:>+6.2f}% | {100 * t['vs_all'][0]:>+6.2f}% [{100 * t['vs_all'][1]:+.2f},{100 * t['vs_all'][2]:+.2f}]"
            f" | {100 * t['vs_vm'][0]:>+6.2f}% [{100 * t['vs_vm'][1]:+.2f},{100 * t['vs_vm'][2]:+.2f}] | {r['ic']:>+.3f}"
        )
    REG.append(
        {
            "experiment_id": f"WINNER_V2_RISK_{label.split()[0]}_{nm.replace('+', '_')}_{mode}",
            "git_commit": COMMIT,
            "working_tree": TREE,
            "model": "lightgbm",
            "params": json.dumps(info),
            "seed": SEED,
            "n_features": nf,
            "ic_2024": round(r["ic"], 4),
            **{
                f"top{t}_{k}": round(r[t][k][0] if isinstance(r[t][k], tuple) else r[t][k], 4)
                for t in (5, 10)
                for k in ("n", "succ", "fail", "net", "vs_all", "vs_vm")
            },
        }
    )


print(
    f"{'target / model':<22}{'vol':>4}{'nf':>4} {'top':>4} {'n/day':>5} {'succ%':>6} {'fail%':>6} | {'net':>7} | {'vs all stocks [95% CI]':>29} | {'vs same-volatility stocks [95% CI]':>34} | IC"
)
for kind, label in (
    ("SvF", "SvF success-v-failure"),
    ("EXR", "EXR exit-return reg"),
    ("PROFIT", "PROFIT beats cost"),
    ("A", "A rises 10% (ref)"),
    ("C", "C success (ref)"),
):
    for nm, mode, cc in EXPS:
        if kind in ("A", "C") and (nm, mode) not in (("V1", "ON"), ("ALL", "ON"), ("V1", "OFF")):
            continue
        ji = [col[c] for c in cc]
        if kind == "SvF":
            rtr = tr & RESOLVED
            mdl, k, info = fit_select("SvF", (OUTC[rtr] == wl.SUCCESS).astype(int), rtr, ji)
        elif kind == "EXR":
            rtr = tr & fin
            mdl, k, info = fit_select("reg", EXR[rtr], rtr, ji)
        elif kind == "PROFIT":
            rtr = tr & fin
            mdl, k, info = fit_select("PROFIT", (EXR[rtr] - COST > 0).astype(int), rtr, ji)
        else:
            mdl, k, info = fit_select(kind, Y[kind][tr], tr, ji)
        xt = X[te & fin][:, ji]
        p = (
            mdl.predict(xt, num_iteration=k)
            if kind == "EXR"
            else mdl.predict_proba(xt, num_iteration=k)[:, 1]
        )
        row(label, mode, len(cc), info, score_trades(p))
    print()
print(
    "net = barrier-trade return after the real cost; 'vs all stocks' subtracts that day's average stock; 'vs same-volatility stocks' subtracts the average of that day's stocks in the same volatility quintile (volatility_20d)."
)
print(
    "A model that only picks volatile stocks scores about 0 in the last column; skill shows as a positive number whose CI excludes 0. IC = mean daily rank correlation of the score with the trade's exit return."
)
keys = sorted({k for r_ in REG for k in r_})
with open(OUT / "risk_register.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=keys)
    w.writeheader()
    w.writerows(REG)
print(
    f"\nregister: {len(REG)} rows -> {OUT / 'risk_register.csv'} (dev period to {DEV_END}); total {time.time() - T0:.0f}s"
)
