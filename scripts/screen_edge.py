# ruff: noqa: E501
"""Do the screener's technical presets find anything? (TODO 6.11.) For each weekly day since 2020, the stocks matching a preset's rules ON THAT DAY (price fields rebuilt from
bars up to the day, as in the score history), and what they did over the next 20 sessions compared with every stock above the preset's own turnover floor that day.
usage: screen_edge.py [--db URL] [--since 2020-06-01]
Prints per preset: stock-weeks matched, average excess return per 4 weeks (match minus the universe AVERAGE that day), share of matches that beat the universe median, a t-stat on
every 4th week (so overlapping windows do not count twice) and the same by year. Windows containing a split or bonus are dropped; returns clipped to -90%..+300%. Before costs."""

import argparse
import os
from datetime import date

import numpy as np
import pandas as pd
import psycopg

from algo.screener import history
from algo.screener.presets import PRESETS

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--since", type=date.fromisoformat, default=date(2020, 6, 1))
ap.add_argument("--horizon", type=int, default=20)
a = ap.parse_args()
H = a.horizon
OPS = {"gt": np.greater, "gte": np.greater_equal, "lt": np.less, "lte": np.less_equal}

with psycopg.connect(a.db) as conn:
    days = history.week_ends(conn, a.since, date.today())
    splits = pd.DataFrame(
        conn.execute(
            "SELECT instrument_id, ex_date FROM corporate_action WHERE kind IN ('split','bonus') AND status='ok'"
        ).fetchall(),
        columns=["instrument_id", "ex_date"],
    )
    frames = []
    for year in range(a.since.year, date.today().year + 1):
        ds = [d for d in days if d.year == year]
        if ds:
            bars = history.load_bars(conn, ds[0], ds[-1])
            frames.append(history.technical_frame(bars, splits, ds, extra=True))
            print(f"  {year}: {len(ds)} days built", flush=True)
    tech = pd.concat(frames, ignore_index=True)
    closes = pd.DataFrame(
        conn.execute(
            "SELECT instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, close::float8 FROM bar_1d WHERE source='nse' AND series='EQ' AND ts >= %s",
            (a.since,),
        ).fetchall(),
        columns=["instrument_id", "d", "close"],
    )

closes = closes.sort_values(["instrument_id", "d"])
closes["fwd"] = closes.groupby("instrument_id")["close"].shift(-H) / closes["close"] - 1
closes["end"] = closes.groupby("instrument_id")["d"].shift(-H)
m = tech.merge(closes[["instrument_id", "d", "fwd", "end"]], on=["instrument_id", "d"]).dropna(
    subset=["fwd"]
)
ex = splits.groupby("instrument_id")["ex_date"].apply(list).to_dict()
bad = np.array(
    [
        any(d < e <= end for e in ex.get(i, []))
        for i, d, end in zip(m["instrument_id"], m["d"], m["end"], strict=True)
    ]
)
m = m[~bad].copy()
m["fwd"] = m["fwd"].clip(-0.9, 3.0)
weeks = sorted(m["d"].unique())
print(f"{len(m)} stock-weeks over {len(weeks)} weeks\n")


def passes(df: pd.DataFrame, conds) -> pd.Series:
    ok = pd.Series(True, index=df.index)
    for c in conds:
        if c.field not in df.columns:
            return pd.Series(False, index=df.index)
        v = df[c.field]
        if c.op == "between":
            ok &= (v >= c.value[0]) & (v <= c.value[1])
        else:
            ok &= OPS[c.op](v, c.value) & v.notna()
    return ok


for p in (p for p in PRESETS if p.category == "technical"):
    floor = next((c.value for c in p.conditions if c.field == "turnover_cr"), 1)
    base = m[m["turnover_cr"] >= floor]
    base = base.assign(
        med=base.groupby("d")["fwd"].transform("mean"),
        mid=base.groupby("d")["fwd"].transform("median"),
    )  # the MEAN is the fair baseline for a mean (returns are right-skewed, so the mean sits above the median by itself)
    hit = base[passes(base, p.conditions)].copy()
    hit["ex"] = hit["fwd"] - hit["med"]
    if len(hit) < 50:
        print(f"{p.name:32s} too few matches ({len(hit)})")
        continue
    per_week = hit.groupby("d")["ex"].mean()
    ind = per_week[::4]  # every 4th week: the 20-session windows do not overlap
    t = (
        ind.mean() / (ind.std() / len(ind) ** 0.5)
        if len(ind) > 3 and ind.std() > 0
        else float("nan")
    )
    yrs = hit.assign(y=pd.to_datetime(hit["d"]).dt.year).groupby("y")["ex"].mean() * 100
    print(
        f"{p.name:32s} n={len(hit):6d} excess {hit['ex'].mean() * 100:+5.2f}%/4wk  beat-median {(hit['fwd'] > hit['mid']).mean():.0%}  t={t:+.1f}  by year {' '.join(f'{int(y) % 100}:{v:+.1f}' for y, v in yrs.items())}"
    )
