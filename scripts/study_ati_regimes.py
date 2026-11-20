# ruff: noqa: E501
"""ATI P2 regime validation (2026-11-19). RESEARCH ONLY, descriptive; the regime thresholds in `algo.ati.regime` (ati-r1) were fixed before this run and are not tuned to it.
Per rule regime: share of stock-days, persistence (mean run length in sessions), transition matrix, and the forward 20-session outcome measured from the close of t (the label side; features
never see it): excess return over the same-day universe mean, hit rate (excess > 0), max favourable / adverse excursion (best high / worst low of sessions t+1..t+20 over close t), by year.
Clusters: K-Means (k = 4, 6, 8) fitted ONLY on 2019-2021 stock-days (scaler included), assigned to 2022-2024; reports size and forward excess per cluster, and stability = adjusted Rand index
of two fits with different seeds on the same test rows. No cluster is called bullish because it did well: read the table, do not name it.
Data: Kite adjusted bars strictly before 2025-01-01 (protected holdout not read).
usage: study_ati_regimes.py [--db URL] [--out FILE]"""

import argparse
import os
import sys

import numpy as np
import pandas as pd
import psycopg
from sklearn.metrics import adjusted_rand_score  # type: ignore[import-untyped]
from study_common import BARS  # noqa: I001

from algo.ati.features import FEATURE_VERSION, compute_features
from algo.ati.regime import (
    CLUSTER_FEATURES,
    NEEDED,
    REGIME_VERSION,
    REGIMES,
    UNKNOWN,
    assign_clusters,
    breadth,
    cluster_matrix,
    fit_clusters,
    market_index,
    rule_regimes,
)

END, FIRST, TRAIN_END, H = "2025-01-01", "2018-06-01", "2022-01-01", 20
GROUPS = ("trend", "momentum", "volatility", "volume", "channel")
ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--out")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
with psycopg.connect(a.db) as conn:
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, open::float8, high::float8, low::float8, close::float8, volume::float8"
        f" FROM {BARS} WHERE source='kite' AND ts >= %s AND (ts AT TIME ZONE 'Asia/Kolkata')::date < %s ORDER BY instrument_id, ts, dataset_version DESC",
        (FIRST, END),
    ).fetchall()
d = pd.DataFrame(rows, columns=["iid", "d", "o", "h", "l", "c", "v"])
del rows
piv = {
    k: d.pivot(index="d", columns="iid", values=k).sort_index() for k in ("o", "h", "l", "c", "v")
}
days = pd.to_datetime(piv["c"].index)
keep = piv["c"].notna().sum().to_numpy() >= 500
o, h, lo, c, v = (piv[k].to_numpy(dtype="float64")[:, keep] for k in ("o", "h", "l", "c", "v"))
del d, piv
t, s = c.shape
need = set(NEEDED) | set(CLUSTER_FEATURES) | {"hist_vol_20"}
f = {m.name: x for m, x in compute_features(o, h, lo, c, v, GROUPS) if m.name in need}
reg = rule_regimes(f)
# forward outcomes (label side: these read the future on purpose, features never do)
with np.errstate(invalid="ignore", divide="ignore"):
    fwd = np.vstack([c[H:] / c[:-H] - 1, np.full((H, s), np.nan)])
    ex = fwd - np.nanmean(fwd, axis=1, keepdims=True)
    mfe, mae = np.full((t, s), -np.inf), np.full((t, s), np.inf)
    for k in range(1, H + 1):
        mfe = np.fmax(mfe, np.vstack([h[k:], np.full((k, s), np.nan)]))
        mae = np.fmin(mae, np.vstack([lo[k:], np.full((k, s), np.nan)]))
    mfe, mae = mfe / c - 1, mae / c - 1
    mfe[~np.isfinite(fwd)] = np.nan
    mae[~np.isfinite(fwd)] = np.nan
yr = days.year.to_numpy()
known = reg != UNKNOWN
out = [
    f"# ATI regime validation ({FEATURE_VERSION} / {REGIME_VERSION})",
    f"stocks {s}, sessions {t}, bars before {END}; forward window {H} sessions from the close of t",
    f"known regime share of stock-days: {known.mean():.3f}",
    "",
    "## Per regime (forward 20-session excess return over the same-day universe mean, %)",
    "",
]
tab = []
for i, name in enumerate(REGIMES):
    m = (reg == i) & np.isfinite(ex)
    starts = (reg == i) & np.vstack([np.zeros((1, s), bool), reg[:-1] != i])
    e = ex[m]
    tab.append(
        (
            name,
            (reg == i).sum() / known.sum(),
            (reg == i).sum() / max(starts.sum(), 1),
            m.sum(),
            e.mean() * 100,
            np.median(e) * 100,
            (e > 0).mean(),
            np.nanmean(mfe[m]) * 100,
            np.nanmean(mae[m]) * 100,
        )
    )
out.append(
    pd.DataFrame(
        tab,
        columns=[
            "regime",
            "share",
            "mean_run",
            "n",
            "excess_mean%",
            "excess_median%",
            "hit",
            "mfe%",
            "mae%",
        ],
    )
    .round(3)
    .to_string(index=False)
)
p0, p1 = reg[:-1], reg[1:]
ok = (p0 != UNKNOWN) & (p1 != UNKNOWN)
tm = np.bincount((p0[ok].astype(int) * 7 + p1[ok]).ravel(), minlength=49).reshape(7, 7)
out += ["", "## Transition matrix (row = today, column = next session; share of the row)", ""]
out.append(
    pd.DataFrame(
        tm / np.maximum(tm.sum(1, keepdims=True), 1),
        index=REGIMES,
        columns=[r[:6] for r in REGIMES],
    )
    .round(3)
    .to_string()
)
out += ["", "## Mean forward excess % by regime and year", ""]
by_year = {}
for i, name in enumerate(REGIMES):
    by_year[name] = {}
    for y in range(2019, 2025):
        sel = (reg == i) & (yr == y)[:, None] & np.isfinite(ex)
        by_year[name][y] = ex[sel].mean() * 100 if sel.any() else np.nan
out.append(pd.DataFrame(by_year).T.round(3).to_string())
# market regime and breadth
mi = market_index(c)[:, None]
mf = {
    m.name: x
    for m, x in compute_features(mi, mi, mi, mi, np.ones_like(mi), GROUPS[:3])
    if m.name in set(NEEDED)
}
mreg = rule_regimes(mf)[:, 0]
br = breadth(f["ema_50_distance"])
out += [
    "",
    "## Market regime (equal-weight index): share of sessions and mean breadth (share of stocks above EMA50)",
    "",
]
out.append(
    pd.DataFrame(
        {
            "share": [(mreg == i).mean() for i in range(7)],
            "breadth": [
                np.nanmean(br[mreg == i]) if (mreg == i).any() else np.nan for i in range(7)
            ],
        },
        index=REGIMES,
    )
    .round(3)
    .to_string()
)
# clusters: fit on 2019-2021, assign 2022-2024
x = cluster_matrix(f, c)
rowday = np.repeat(np.arange(t), s)
tr = (days[rowday] >= "2019-01-01") & (days[rowday] < TRAIN_END)
te = (days[rowday] >= TRAIN_END) & np.isfinite(ex.ravel())
exr = ex.ravel()[te]
out += [
    "",
    f"## K-Means (fit on 2019-2021 only, assigned to 2022-2024; features {', '.join(CLUSTER_FEATURES)})",
    "",
]
for k in (4, 6, 8):
    lab0 = assign_clusters(fit_clusters(x[tr], k, seed=0), x[te])
    lab1 = assign_clusters(fit_clusters(x[tr], k, seed=1), x[te])
    good = (lab0 >= 0) & (lab1 >= 0)
    out.append(
        f"k={k}: stability (adjusted Rand index, seed 0 vs 1, test rows) = {adjusted_rand_score(lab0[good], lab1[good]):.3f}"
    )
    out.append(
        pd.DataFrame(
            [
                (j, (lab0 == j).mean(), exr[lab0 == j].mean() * 100, (exr[lab0 == j] > 0).mean())
                for j in range(k)
            ],
            columns=["cluster", "share", "excess_mean%", "hit"],
        )
        .round(3)
        .to_string(index=False)
    )
    out.append("")
text = "\n".join(out)
if a.out:
    open(a.out, "w").write(text + "\n")
print(text)
