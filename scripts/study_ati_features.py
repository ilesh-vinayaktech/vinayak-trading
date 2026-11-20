# ruff: noqa: E501
"""ATI P1 baseline feature report (2026-11-19). RESEARCH ONLY, descriptive: it reports NO predictive claim.
For every feature of `algo.ati.features` (version ati-f1): coverage (share of stock-days non-NaN), mean, std, 1/99 percentiles, and the feature pairs with |Spearman| >= 0.9
(correlated indicators are not independent confirmations: spec 7.3). Data: Kite adjusted bars strictly before 2025-01-01 (protected holdout not read).
usage: study_ati_features.py [--db URL] [--out FILE]"""

import argparse
import os
import sys

import numpy as np
import pandas as pd
import psycopg
from study_common import BARS  # noqa: I001

from algo.ati.features import FEATURE_VERSION, compute_features

END, FIRST = "2025-01-01", "2018-06-01"
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


def mat(col: str) -> np.ndarray:
    return d.pivot(index="d", columns="iid", values=col).sort_index().to_numpy(dtype="float64")


days = d["d"].nunique()
o, h, lo, c, v = (mat(k) for k in ("o", "h", "l", "c", "v"))
keep = np.isfinite(c).sum(0) >= 500  # at least two years of bars
o, h, lo, c, v = (x[:, keep] for x in (o, h, lo, c, v))
rng = np.random.default_rng(0)
sample = (
    np.sort(rng.choice(c.shape[0] - 300, size=150, replace=False)) + 300
)  # fixed-seed day sample for the correlation table
stats, cols = [], {}
for meta, arr in compute_features(o, h, lo, c, v):
    x = arr.astype("float64")
    ok = np.isfinite(x)
    q = np.nanpercentile(x, [1, 99]) if ok.any() else (np.nan, np.nan)
    stats.append(
        (
            meta.name,
            meta.group,
            meta.lookback,
            ok.mean(),
            np.nanmean(x) if ok.any() else np.nan,
            np.nanstd(x) if ok.any() else np.nan,
            q[0],
            q[1],
        )
    )
    if not meta.name.startswith("st_") or meta.name.startswith(
        "st_14_3_0"
    ):  # one SuperTrend config stands for the grid in the correlation table
        cols[meta.name] = pd.Series(x[sample].ravel())
st = pd.DataFrame(
    stats, columns=["feature", "group", "lookback", "coverage", "mean", "std", "p1", "p99"]
)
cor = pd.DataFrame(cols).corr(method="spearman")
pairs = [
    (i, j, cor.loc[i, j])
    for k, i in enumerate(cor.columns)
    for j in cor.columns[k + 1 :]
    if abs(cor.loc[i, j]) >= 0.9
]
out = [
    f"# ATI baseline feature report ({FEATURE_VERSION})",
    f"stocks {c.shape[1]}, sessions {days}, bars before {END}",
    "",
]
out.append(st.round(4).to_string(index=False))
out += [
    "",
    f"## Pairs with |Spearman| >= 0.9 ({len(pairs)}; SuperTrend grid represented by ATR 14 x3.0)",
    "",
]
out += [f"- {i} ~ {j}: {r:+.2f}" for i, j, r in sorted(pairs, key=lambda p: -abs(p[2]))]
text = "\n".join(out)
if a.out:
    open(a.out, "w").write(text + "\n")
print(text)
