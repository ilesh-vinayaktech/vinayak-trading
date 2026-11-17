# ruff: noqa: E501, B023
"""Did the swing score predict anything? (TODO 6.2a check; the full learning loop is 6.5.)
usage: score_edge.py [--db URL]   (needs stock_score_history: scripts/build_score_history.py --all)
For every stored day: each stock's return over the next 20 sessions (windows containing a split or bonus are dropped, returns clipped to -90%..+300%), minus the
average stock that day. Prints, for the score and each component: the average excess return of each fifth (bottom to top), top minus bottom, the rank
correlation with the next return (IC, with a t-stat that is OVERSTATED because weekly 4-week windows overlap) and the share of weeks it was positive; then the
score's fifths by year. Before costs, equal weight over the scored stocks (liquid, 5 crore a day or more). Read-only."""

import argparse
import os

import numpy as np
import pandas as pd
import psycopg
from scipy.stats import spearmanr

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
a = ap.parse_args()
c = psycopg.connect(a.db)
s = pd.DataFrame(
    c.execute(
        "select day,instrument_id,score,trend,participation,smart_money,quality from stock_score_history"
    ).fetchall(),
    columns=["day", "iid", "score", "trend", "participation", "smart_money", "quality"],
)
b = pd.DataFrame(
    c.execute(
        "select instrument_id,(ts at time zone 'Asia/Kolkata')::date,close::float8 from (select distinct on (instrument_id,ts) * from bar_1d where source='nse' order by instrument_id,ts,dataset_version desc) x"
    ).fetchall(),
    columns=["iid", "d", "close"],
)
sp = pd.DataFrame(
    c.execute(
        "select instrument_id,ex_date from corporate_action where kind in ('split','bonus') and status='ok'"
    ).fetchall(),
    columns=["iid", "ex"],
)
b = b.sort_values(["iid", "d"])
H = 20
b["fwd"] = b.groupby("iid")["close"].shift(-H) / b["close"] - 1
b["end"] = b.groupby("iid")["d"].shift(-H)
m = s.merge(b[["iid", "d", "fwd", "end"]], left_on=["iid", "day"], right_on=["iid", "d"]).dropna(
    subset=["fwd"]
)
# drop windows containing a split
spd = sp.groupby("iid")["ex"].apply(list).to_dict()
bad = [
    any(day < e <= end for e in spd.get(i, []))
    for i, day, end in zip(m.iid, m.day, m.end, strict=True)
]
m = m[~np.array(bad)]
m["fwd"] = m["fwd"].clip(-0.9, 3)  # tame data errors
m["mkt"] = m.groupby("day")["fwd"].transform(
    "mean"
)  # the AVERAGE stock: returns are right-skewed, so the median sits below the mean and would flatter every bucket
m["ex"] = m["fwd"] - m["mkt"]
print("rows", len(m), "days", m.day.nunique())
for col in ["score", "trend", "participation", "smart_money", "quality"]:
    x = m.dropna(subset=[col]).copy()
    x["q"] = x.groupby("day")[col].transform(
        lambda v: pd.qcut(v.rank(method="first"), 5, labels=False)
    )
    q = x.groupby("q")["ex"].mean() * 100
    ic = x.groupby("day").apply(lambda g: spearmanr(g[col], g["fwd"])[0]).dropna()
    print(
        f"{col:14s} n={len(x):6d} top-minus-bottom quintile excess {q[4] - q[0]:+.2f}%/4wk  quintiles {[round(v, 2) for v in q]}  IC mean {ic.mean():+.3f} t={ic.mean() / ic.std() * len(ic) ** 0.5:.1f} hit {ic.gt(0).mean():.0%}"
    )
x = m.copy()
x["yr"] = pd.to_datetime(x.day).dt.year
x["q"] = x.groupby("day")["score"].transform(
    lambda v: pd.qcut(v.rank(method="first"), 5, labels=False)
)
print((x.groupby(["yr", "q"])["ex"].mean().unstack() * 100).round(2))
