# ruff: noqa: E501
"""ATI P2 benchmarks and GMM comparison (2026-11-19). RESEARCH ONLY, descriptive; the rule thresholds (ati-r1) are the ones of the first report, untouched.
Forward 20-session return from the close of t, measured against three same-day benchmarks (label side; features never see it):
  universe   all stocks (as in regime_report_r1)          vol-matched   stocks in the same same-day decile of hist_vol_20 (known at t)
  sector     stocks of the same sector (instrument_sector snapshot 2026-11-10 = CURRENT Nifty 500 members only, not point-in-time: indicative, and a survivor-biased subset)
Per rule regime: mean excess against each benchmark and, for vol-matched, a stationary-bootstrap CI of the per-date means (block 20, 500 resamples; Bonferroni-widened to 99.3% because 7 regimes are tested), plus the year-by-year mean.
Clustering, 2019-2021 fit / 2022-2024 test: K-Means vs Gaussian mixture (k = 4, 6, 8; GMM BIC on its training sample, seed stability by adjusted Rand index, tiny components flagged), and for rule regimes / K-Means / GMM at
k = 6: eta-squared = share of the test-period vol-matched excess variance explained by the labels, plus adjusted mutual information with the rule regimes.
Data: Kite adjusted bars strictly before 2025-01-01 (protected holdout not read).
usage: study_ati_benchmarks.py [--db URL] [--out FILE]"""

import argparse
import os
import sys

import numpy as np
import pandas as pd
import psycopg
from sklearn.metrics import (  # type: ignore[import-untyped]
    adjusted_mutual_info_score,
    adjusted_rand_score,
)
from study_common import BARS  # noqa: I001

from algo.ati.benchmark import group_excess, vol_deciles
from algo.ati.features import FEATURE_VERSION, compute_features
from algo.ati.regime import (
    CLUSTER_FEATURES,
    NEEDED,
    REGIME_VERSION,
    REGIMES,
    UNKNOWN,
    assign_clusters,
    cluster_matrix,
    fit_clusters,
    rule_regimes,
)
from algo.backtest.validation.stats import bootstrap_interval

END, FIRST, TRAIN_END, H = "2025-01-01", "2018-06-01", "2022-01-01", 20
GROUPS = ("trend", "momentum", "volatility", "volume", "channel")
CONF = 1 - 0.05 / len(REGIMES)
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
    sec = dict(conn.execute("SELECT instrument_id, sector FROM instrument_sector").fetchall())
d = pd.DataFrame(rows, columns=["iid", "d", "o", "h", "l", "c", "v"])
del rows
piv = {
    k: d.pivot(index="d", columns="iid", values=k).sort_index() for k in ("o", "h", "l", "c", "v")
}
days = pd.to_datetime(piv["c"].index)
keep = piv["c"].notna().sum().to_numpy() >= 500
iids = piv["c"].columns[keep]
o, h, lo, c, v = (piv[k].to_numpy(dtype="float64")[:, keep] for k in ("o", "h", "l", "c", "v"))
del d, piv
t, s = c.shape
need = set(NEEDED) | set(CLUSTER_FEATURES) | {"hist_vol_20"}
f = {m.name: x for m, x in compute_features(o, h, lo, c, v, GROUPS) if m.name in need}
del o, h, lo, v
reg = rule_regimes(f)
with np.errstate(invalid="ignore", divide="ignore"):
    fwd = np.vstack([c[H:] / c[:-H] - 1, np.full((H, s), np.nan)])
ex_u = fwd - np.nanmean(fwd, axis=1, keepdims=True)
ex_v = group_excess(fwd, vol_deciles(f["hist_vol_20"]), 10)
names = sorted(set(sec.values()))
scode = np.array([names.index(sec[i]) if i in sec else -1 for i in iids])
ex_s = group_excess(fwd, np.broadcast_to(scode, fwd.shape), len(names))
yr = days.year.to_numpy()
out = [
    f"# ATI benchmarks and GMM ({FEATURE_VERSION} / {REGIME_VERSION})",
    f"stocks {s} ({(scode >= 0).sum()} with a sector), sessions {t}, bars before {END}; forward window {H} sessions; CI level {CONF:.4f} (Bonferroni over {len(REGIMES)} regimes)",
    "",
    "## Per rule regime: mean forward excess % against three benchmarks (vol-matched CI from per-date means)",
    "",
]


def mean_ci(mask: np.ndarray) -> tuple[float, float, float]:
    cnt = (mask & np.isfinite(ex_v)).sum(1)
    per_date = np.where(mask & np.isfinite(ex_v), ex_v, 0.0).sum(1) / np.maximum(cnt, 1)
    series = [float(x) for x in per_date[cnt >= 30]]
    iv = (
        bootstrap_interval(
            series, lambda xs: sum(xs) / len(xs), n_boot=500, mean_block=20, confidence=CONF, seed=0
        )
        if len(series) > 40
        else None
    )
    return (iv.point, iv.low, iv.high) if iv else (np.nan, np.nan, np.nan)


tab = []
for i, name in enumerate(REGIMES):
    m = reg == i
    lo_, hi_ = mean_ci(m)[1:]
    sm = m & np.isfinite(ex_s)
    tab.append(
        (
            name,
            (m & np.isfinite(ex_u)).sum(),
            np.nanmean(ex_u[m]) * 100,
            np.nanmean(ex_v[m]) * 100,
            lo_ * 100,
            hi_ * 100,
            (ex_v[m][np.isfinite(ex_v[m])] > 0).mean(),
            sm.sum(),
            np.nanmean(ex_s[sm]) * 100 if sm.any() else np.nan,
            np.nanmean(ex_v[sm]) * 100 if sm.any() else np.nan,
        )
    )
out.append(
    pd.DataFrame(
        tab,
        columns=[
            "regime",
            "n",
            "vs_universe%",
            "vs_vol%",
            "vol_lo%",
            "vol_hi%",
            "vol_hit",
            "n_sector",
            "vs_sector%",
            "vs_vol_same_stocks%",
        ],
    )
    .round(3)
    .to_string(index=False)
)
out += ["", "## Mean vol-matched excess % by regime and year", ""]
by = {
    name: {
        y: (
            np.nanmean(ex_v[(reg == i) & (yr == y)[:, None]]) * 100
            if ((reg == i) & (yr == y)[:, None] & np.isfinite(ex_v)).any()
            else np.nan
        )
        for y in range(2019, 2025)
    }
    for i, name in enumerate(REGIMES)
}
out.append(pd.DataFrame(by).T.round(3).to_string())
# clustering comparison
x = cluster_matrix(f, c)
rowday = np.repeat(np.arange(t), s)
tr = (days[rowday] >= "2019-01-01") & (days[rowday] < TRAIN_END)
te = (days[rowday] >= TRAIN_END) & np.isfinite(ex_v.ravel())
exv = ex_v.ravel()[te]
rr = reg.ravel()[te]


def eta2(lab: np.ndarray) -> float:
    ok = lab >= 0
    y, g = exv[ok], lab[ok]
    tot = ((y - y.mean()) ** 2).sum()
    gm = pd.Series(y).groupby(g).transform("mean").to_numpy()
    return float(((gm - y.mean()) ** 2).sum() / tot)


out += ["", "## K-Means vs Gaussian mixture (fit 2019-2021, test 2022-2024)", ""]
labs6: dict[str, np.ndarray] = {}
for method in ("kmeans", "gmm"):
    for k in (4, 6, 8):
        m0, m1 = (
            fit_clusters(x[tr], k, seed=0, method=method),
            fit_clusters(x[tr], k, seed=1, method=method),
        )
        l0, l1 = assign_clusters(m0, x[te]), assign_clusters(m1, x[te])
        good = (l0 >= 0) & (l1 >= 0)
        bic = ""
        if method == "gmm":
            z = (x[tr][np.isfinite(x[tr]).all(1)][:100_000] - m0.mean) / m0.std
            bic = f", BIC(train sample) = {m0.km.bic(z):.0f}"
        rows_c = [
            (j, (l0 == j).sum(), exv[l0 == j].mean() * 100, (exv[l0 == j] > 0).mean())
            for j in range(k)
        ]
        small = [j for j, n, _, _ in rows_c if n < 1000]
        out.append(
            f"{method} k={k}: stability (ARI seed 0 vs 1) = {adjusted_rand_score(l0[good], l1[good]):.3f}{bic}; eta2 = {eta2(l0):.5f}; components under 1000 test rows: {small}"
        )
        out.append(
            pd.DataFrame(rows_c, columns=["cluster", "n_test", "vol_excess_mean%", "hit"])
            .round(3)
            .to_string(index=False)
        )
        out.append("")
        if k == 6:
            labs6[method] = l0
ok = rr != UNKNOWN
out += [
    "## Explained share (eta-squared) of the test-period vol-matched excess variance, and agreement with the rule regimes (k = 6)",
    "",
]
rows_e = [("rule regimes (7)", eta2(np.where(ok, rr, -1)), np.nan)] + [
    (
        m_,
        eta2(labs6[m_]),
        adjusted_mutual_info_score(rr[ok & (labs6[m_] >= 0)], labs6[m_][ok & (labs6[m_] >= 0)]),
    )
    for m_ in ("kmeans", "gmm")
]
out.append(
    pd.DataFrame(rows_e, columns=["labels", "eta2", "AMI_with_rules"])
    .round(5)
    .to_string(index=False)
)
text = "\n".join(out)
if a.out:
    open(a.out, "w").write(text + "\n")
print(text)
