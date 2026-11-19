# ruff: noqa: E501
"""Study: do the smart-money readings on the instrument page (delivery vs its average, holding changes, insider and deal flow)
say anything about the next 20 sessions? Every signal is taken as it was KNOWN on the day (algo.screener.history.smart_fields; delivery
from the day's bar and the 20 sessions before it), the return is close(day + 20 sessions) / close(day) - 1 less the median of that day's
liquid stocks, and a window that crosses a split or bonus is dropped. Weekly days from 2019-11 (NSE delivery begins 2019-10).
usage: tune_smart_money.py [--db URL] [--horizon 20] [--min-turnover-cr 5]"""

import argparse
import os
import sys
from datetime import date

import numpy as np
import pandas as pd
import psycopg

from algo.screener.history import smart_fields, week_ends

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--horizon", type=int, default=20)
ap.add_argument("--min-turnover-cr", type=float, default=5.0)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
H = a.horizon

with psycopg.connect(a.db) as conn:
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, close::float8, volume::float8,"
        " CASE WHEN series = 'EQ' THEN delivery_qty::float8 END FROM bar_1d WHERE source='nse' AND series='EQ' AND ts >= '2019-09-01'"
        " ORDER BY instrument_id, ts, dataset_version DESC"
    ).fetchall()
    splits = conn.execute(
        "SELECT instrument_id, ex_date FROM corporate_action WHERE kind IN ('split','bonus') AND status='ok'"
    ).fetchall()
    sym = dict(
        conn.execute(
            "SELECT instrument_id, symbol FROM instrument WHERE asset_class='equity'"
        ).fetchall()
    )
    last = max(r[1] for r in rows)
    days = [d for d in week_ends(conn, date(2019, 11, 1), last)]
    smart = smart_fields(conn, days)

df = pd.DataFrame(rows, columns=["iid", "d", "close", "volume", "deliv"])
close = df.pivot(index="d", columns="iid", values="close").sort_index()
vol = df.pivot(index="d", columns="iid", values="volume").reindex(close.index)
dq = df.pivot(index="d", columns="iid", values="deliv").reindex(close.index)
del df, rows
dpct = 100 * dq / vol.where(vol > 0)
ratio = dpct / dpct.shift(1).rolling(20, min_periods=15).mean()
turnover_cr = (close * vol).rolling(20, min_periods=15).mean() / 1e7
fwd = close.shift(-H) / close - 1
pos = {d: i for i, d in enumerate(close.index)}
for iid, ex in splits:  # a window that crosses a split or bonus is not a return
    if iid in fwd.columns:
        i = int(np.searchsorted(close.index.values, np.datetime64(ex)))
        fwd.iloc[max(0, i - H) : i, fwd.columns.get_loc(iid)] = np.nan

recs = []
for d in days:
    if d not in pos or pos[d] + H >= len(close.index):
        continue
    liquid = turnover_cr.loc[d] >= a.min_turnover_cr
    f = fwd.loc[d][liquid].dropna()
    if len(f) < 100:
        continue
    ex = f - f.median()
    for iid, e in ex.items():
        s = smart.get((d, sym.get(iid, "")), {})
        recs.append(
            {"d": d, "iid": iid, "ex": e, "ratio": ratio.loc[d, iid], "dpct": dpct.loc[d, iid], **s}
        )
t = pd.DataFrame(recs)
print(
    f"{len(t):,} stock-weeks, {t['d'].nunique()} weeks, {t['d'].min()} to {t['d'].max()}, horizon {H} sessions, turnover >= {a.min_turnover_cr} Cr\n"
)


def table(name: str, col: str, edges: list[float], labels: list[str], mask=None) -> None:
    x = t if mask is None else t[mask]
    x = x[x[col].notna()].copy()
    x["bin"] = pd.cut(x[col], edges, labels=labels, right=False)
    print(f"--- {name}")
    print(
        f"{'bucket':<14}{'stock-weeks':>12}{'mean excess %':>15}{'median %':>10}{'beat mkt %':>12}{'t (by week)':>13}"
    )
    for lab, g in x.groupby("bin", observed=True):
        per_week = g.groupby("d")["ex"].mean()
        tstat = (
            per_week.mean() / (per_week.std() / np.sqrt(len(per_week)))
            if len(per_week) > 5 and per_week.std() > 0
            else float("nan")
        )
        print(
            f"{lab!s:<14}{len(g):>12,}{100 * g['ex'].mean():>15.2f}{100 * g['ex'].median():>10.2f}{100 * (g['ex'] > 0).mean():>12.1f}{tstat:>13.2f}"
        )
    print()


inf = np.inf
table(
    "Delivery today vs its own 20-session average (x)",
    "ratio",
    [0, 0.6, 0.8, 1.2, 1.5, 2.0, inf],
    ["<0.6", "0.6-0.8", "0.8-1.2", "1.2-1.5", "1.5-2.0", ">=2.0"],
)
table(
    "Delivery % today (level)",
    "dpct",
    [0, 20, 35, 50, 65, 101],
    ["<20", "20-35", "35-50", "50-65", ">=65"],
)
pts = [-inf, -1, -0.25, 0.25, 1, inf]
lab = ["<=-1", "-1..-0.25", "steady", "0.25..1", ">=1"]
for k, n in (
    ("promoter_change", "Promoter"),
    ("fii_change", "FII"),
    ("dii_change", "DII"),
    ("mf_change", "Mutual funds"),
):
    if k in t:
        table(
            f"{n} holding change vs previous quarter (pts), latest filing known that day",
            k,
            pts,
            lab,
        )
if "insider_net_90d" in t:
    table(
        "Insider net buying, last 90 days (Rs Cr)",
        "insider_net_90d",
        [-inf, -1, -0.05, 0.05, 1, inf],
        ["<=-1 sold", "-1..-0.05", "none", "0.05..1", ">=1 bought"],
    )
if "deal_net_30d" in t:
    table(
        "Bulk/block deal net, last 30 days (Rs Cr)",
        "deal_net_30d",
        [-inf, -10, -1, 1, 10, inf],
        ["<=-10 sold", "-10..-1", "~0", "1..10", ">=10 bought"],
    )

# does the delivery-level step hold in every year, or is it one regime?
print("--- Delivery % level, share of stock-weeks that beat the market, by year (50 = no edge)")
y = t[t["dpct"].notna()].copy()
y["year"] = pd.to_datetime(y["d"]).dt.year
y["lvl"] = pd.cut(y["dpct"], [0, 35, 50, 101], labels=["<35", "35-50", ">=50"], right=False)
print(
    (
        y.groupby(["year", "lvl"], observed=True)["ex"]
        .apply(lambda s: 100 * (s > 0).mean())
        .unstack()
        .round(1)
    ).to_string()
)
print(
    "\n--- Institutions adding (any of FII, DII, MF up >= 0.25 pts, none down >= 0.25) vs the rest, beat-market %, by year"
)
c = [k for k in ("fii_change", "dii_change", "mf_change") if k in t]
z = t[t[c].notna().any(axis=1)].copy()
up = (z[c] >= 0.25).any(axis=1) & ~(z[c] <= -0.25).any(axis=1)
z["grp"] = np.where(up, "adding", "other")
z["year"] = pd.to_datetime(z["d"]).dt.year
print(
    (
        z.groupby(["year", "grp"])["ex"].apply(lambda s: 100 * (s > 0).mean()).unstack().round(1)
    ).to_string(),
    "\n n:",
    z["grp"].value_counts().to_dict(),
)
