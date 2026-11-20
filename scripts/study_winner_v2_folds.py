# ruff: noqa: E501
"""Early-large-upside research V2: is the risk-adjusted edge there in EVERY year, or was 2024 a lucky pick? Rolling-origin folds, development period only.

Folds (expanding training window, trees/config chosen on the year before the test year only, gaps >= 20 sessions asserted):
  test 2022: train to 2020-11-30, select 2021;   test 2023: train to 2021-11-30, select 2022;   test 2024: train to 2022-11-30, select 2023 (as study_winner_v2_risk.py).
2025-01-01 onward is never read. Fold 2022 trains on only about 14 months (from 2019-09), so it is the weakest fold by construction.
Setups (shortlisted from study_winner_v2_risk.py; the choice was made on 2024, so this check is what tests it): the exit-return regressor EXR and the success-vs-failure classifier SvF on V1 / V1 without
volatility features / V1+price+volume+early without volatility / ALL / VOL_ONLY, plus the earlier classifiers A and C as references.
Per fold and pooled: the barrier trade (+10% / -5% from the next open, 10 sessions) of the top 5% of each day, net of the repo's real cost, and against the average stock of the SAME day and the same volatility quintile
(a model that only picks volatile stocks scores 0 there). 95% CI by a 15-day moving-block bootstrap over dates (the pooled one over the three test years together).
usage: study_winner_v2_folds.py [--db URL] [--out DIR] [--min-turnover-cr 5]"""

import argparse
import csv
import os
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
day_of, dts, Y, OUTC, EXR, names, col, X = D.day_of, D.dts, D.Y, D.OUT, D.EXR, D.names, D.col, D.X
COST = flat_cost()
fin = np.isfinite(EXR)
RESOLVED = np.isin(OUTC, (wl.SUCCESS, wl.FAILURE))
vol20 = X[:, col["volatility_20d"]]
T = pd.Timestamp
FOLDS = [  # (test year, train end, select start, select end, test start, test end)
    ("2022", T("2020-11-30"), T("2021-01-04"), T("2021-11-30"), T("2022-01-03"), T("2022-12-31")),
    ("2023", T("2021-11-30"), T("2022-01-03"), T("2022-11-30"), T("2023-01-02"), T("2023-12-31")),
    ("2024", T("2022-11-30"), T("2023-01-02"), T("2023-11-30"), T("2024-01-02"), T("2024-12-31")),
]
V1 = [n for n in names if wf.META[n].group == "v1"]
GRP = {g: [n for n in names if wf.META[n].group == g] for g in wf.GROUPS}


def nov(cols: list[str]) -> list[str]:
    return [c for c in cols if not wf.META[c].volatility]


PVE = V1 + GRP["price"] + GRP["volume"] + GRP["early"]
ALL = PVE + GRP["volatility"]
SETUPS: list[tuple[str, str, str, list[str]]] = [  # (label, kind, vol mode, columns)
    ("EXR", "reg", "OFF", nov(V1)),
    ("EXR", "reg", "ON", V1),
    ("EXR", "reg", "OFF", nov(PVE)),
    ("EXR", "reg", "ON", ALL),
    ("EXR", "reg", "ON", [n for n in names if wf.META[n].volatility]),
    ("SvF", "SvF", "OFF", nov(V1)),
    ("SvF", "SvF", "ON", V1),
    ("SvF", "SvF", "OFF", nov(PVE)),
    ("A (ref)", "A", "ON", V1),
    ("C (ref)", "C", "ON", V1),
]
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


def daily_ic(days: np.ndarray, s: np.ndarray, y: np.ndarray) -> np.ndarray:
    df = pd.DataFrame({"d": days, "s": s, "y": y})
    a_, b_ = df.groupby("d")["s"].rank(pct=True), df.groupby("d")["y"].rank(pct=True)
    a_, b_ = a_ - a_.groupby(df["d"]).transform("mean"), b_ - b_.groupby(df["d"]).transform("mean")
    return (
        (a_ * b_).groupby(df["d"]).sum()
        / np.sqrt((a_**2).groupby(df["d"]).sum() * (b_**2).groupby(df["d"]).sum())
    ).to_numpy()


def fit_select(kind: str, tr: np.ndarray, va: np.ndarray, ji: list[int]) -> tuple[Any, int]:
    """Fit each config once on the training rows; pick (config, trees in 100/200/300) by the SELECTION year only (AUC for a classifier, mean daily rank IC with the trade return for the regressor)."""
    if kind == "reg":
        rtr, vsel, y = tr & fin, va & fin, EXR
    elif kind == "SvF":
        rtr, vsel, y = tr & RESOLVED, va & RESOLVED, (OUTC == wl.SUCCESS).astype(int)
    else:
        rtr, vsel, y = tr, va, Y[kind[0]]
    best: tuple[float, Any, int] | None = None
    for cfg in CONFIGS:
        mdl = (lgb.LGBMRegressor if kind == "reg" else lgb.LGBMClassifier)(**PARAMS, **cfg).fit(
            X[rtr][:, ji], y[rtr]
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
                    y[vsel], mdl.predict_proba(X[vsel][:, ji], num_iteration=k)[:, 1]
                )
            if best is None or sc > best[0]:
                best = (sc, mdl, k)
    assert best is not None
    return best[1], best[2]


def boot_mean(x: np.ndarray, block: int = 15, reps: int = 1000) -> tuple[float, float, float]:
    n = len(x)
    starts = np.random.default_rng(SEED).integers(0, n, (reps, -(-n // block)))
    est = x[((starts[:, :, None] + np.arange(block)) % n).reshape(reps, -1)[:, :n]].mean(1)
    return float(x.mean()), float(np.percentile(est, 2.5)), float(np.percentile(est, 97.5))


def trade_days(score: np.ndarray, te: np.ndarray) -> dict[str, Any]:
    """Top 5% of each test day: per-day net return, per-day edge over all stocks and over same-volatility stocks; plus the rank IC."""
    df = pd.DataFrame({"d": day_of[te], "s": score, "x": EXR[te], "v": vol20[te], "o": OUTC[te]})
    df["rk"] = df.groupby("d")["s"].rank(pct=True)
    df["vq"] = (df.groupby("d")["v"].rank(pct=True) * 5).clip(upper=4.999).fillna(-1).astype(int)
    df["xu"] = df.groupby("d")["x"].transform("mean")
    df["xm"] = df.groupby(["d", "vq"])["x"].transform("mean")
    g = df[df["rk"] > 0.95].groupby("d")
    return {
        "net": (g["x"].mean() - COST).to_numpy(),
        "vs_all": (g["x"].mean() - g["xu"].mean()).to_numpy(),
        "vs_vm": (g["x"].mean() - g["xm"].mean()).to_numpy(),
        "ic": float(
            np.nanmean(daily_ic(df["d"].to_numpy(), df["s"].to_numpy(), df["x"].to_numpy()))
        ),
    }


def fmt(b: tuple[float, float, float]) -> str:
    return f"{100 * b[0]:+.2f} [{100 * b[1]:+.2f},{100 * b[2]:+.2f}]"


print(
    f"\nreal round-trip cost {100 * COST:.2f}%; barrier trade +10% / -5% from the next open, 10 sessions; top 5% of each day; development period to {DEV_END}\n"
)
print("the trade with no selection (all stocks) per test year:")
for yr, _tre, _s0, _s1, t0, t1 in FOLDS:
    te = (dts >= t0) & (dts <= t1)
    x = EXR[te & fin]
    print(
        f"  {yr}: gross {100 * x.mean():+.2f}%, net {100 * (x.mean() - COST):+.2f}%; success {100 * (OUTC[te & fin] == wl.SUCCESS).mean():.1f}%, failure {100 * (OUTC[te & fin] == wl.FAILURE).mean():.1f}%"
    )

RES: dict[tuple[int, int], dict[str, Any]] = {}
for fi, (yr, tre, s0, s1, t0, t1) in enumerate(FOLDS):
    tr_, va_, te_ = dts <= tre, (dts >= s0) & (dts <= s1), (dts >= t0) & (dts <= t1)
    g1, g2 = day_of[va_].min() - day_of[tr_].max(), day_of[te_].min() - day_of[va_].max()
    assert g1 >= 20 and g2 >= 20, (yr, g1, g2)
    print(
        f"\nfold {yr}: train {int(tr_.sum()):,} (to {tre.date()}), select {int(va_.sum()):,}, test {int(te_.sum()):,}; gaps {g1} and {g2} sessions; {time.time() - T0:.0f}s",
        flush=True,
    )
    for si, (_label, kind, _mode, cc) in enumerate(SETUPS):
        ji = [col[c] for c in cc]
        mdl, k = fit_select(kind, tr_, va_, ji)
        xt = X[te_ & fin][:, ji]
        p = (
            mdl.predict(xt, num_iteration=k)
            if kind == "reg"
            else mdl.predict_proba(xt, num_iteration=k)[:, 1]
        )
        RES[(si, fi)] = trade_days(p, te_ & fin)

print(
    "\n=== top 5% of each day, barrier trade, per test year: net after cost | edge over the same-volatility stocks [95% CI], in %. Pooled = the three years together."
)
print(
    f"{'setup':<9}{'vol':>4}{'nf':>4} | "
    + " | ".join(f"{'test ' + f[0] + ': net | edge vs same-vol':^37}" for f in FOLDS)
    + f" | {'POOLED edge vs same-vol':^26} | yrs CI>0 | net pooled"
)
REG: list[dict[str, object]] = []
for si, (label, _kind, mode, cc) in enumerate(SETUPS):
    cells, pos = [], 0
    for fi in range(len(FOLDS)):
        r = RES[(si, fi)]
        b = boot_mean(r["vs_vm"])
        pos += int(b[1] > 0)
        cells.append(f"{100 * float(np.mean(r['net'])):+.2f} | {fmt(b)}")
    pooled = boot_mean(np.concatenate([RES[(si, fi)]["vs_vm"] for fi in range(len(FOLDS))]))
    pooled_all = boot_mean(np.concatenate([RES[(si, fi)]["vs_all"] for fi in range(len(FOLDS))]))
    pooled_net = float(np.mean(np.concatenate([RES[(si, fi)]["net"] for fi in range(len(FOLDS))])))
    print(
        f"{label:<9}{mode:>4}{len(cc):>4} | "
        + " | ".join(f"{c:^37}" for c in cells)
        + f" | {fmt(pooled):^26} | {pos}/3      | {100 * pooled_net:+.2f}"
    )
    REG.append(
        {
            "experiment_id": f"WINNER_V2_FOLDS_{label.split()[0]}_{mode}_{len(cc)}",
            "n_features": len(cc),
            "pooled_vs_same_vol": round(pooled[0], 5),
            "pooled_vs_same_vol_lo": round(pooled[1], 5),
            "pooled_vs_same_vol_hi": round(pooled[2], 5),
            "pooled_vs_all": round(pooled_all[0], 5),
            "pooled_net": round(pooled_net, 5),
            "years_ci_positive": pos,
            "seed": SEED,
            "dev_end": DEV_END,
        }
    )
print("\nrank IC of the score with the trade's exit return, per test year (2022 / 2023 / 2024):")
for si, (label, _kind, mode, cc) in enumerate(SETUPS):
    print(
        f"  {label:<9}{mode:>4}{len(cc):>4}  "
        + "  ".join(f"{RES[(si, fi)]['ic']:+.3f}" for fi in range(len(FOLDS)))
    )
keys = sorted({k for r_ in REG for k in r_})
with open(OUT / "folds_register.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=keys)
    w.writeheader()
    w.writerows(REG)
print(f"\nregister: {len(REG)} rows -> {OUT / 'folds_register.csv'}; total {time.time() - T0:.0f}s")
