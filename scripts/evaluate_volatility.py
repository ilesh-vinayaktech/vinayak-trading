# ruff: noqa: E501
"""Evaluate the volatility forecast (algo.market.volatility) on DEVELOPMENT data only: sessions up to algo.factory.study.WINDOW[1] (2024-12-31); the 2025 holdout is never read.
Targets: the next session's high-low range as % of its open (primary) and its absolute close-to-close move (secondary), both for the Nifty 500, forecast before the open.
Walk-forward predictions are compared with simple baselines on identical sessions, with block-bootstrap intervals, by volatility regime and by year, and with the inputs removed one group at a time.
usage: evaluate_volatility.py [--db URL] [--out docs/forecast/volatility_dev_<date>.md]"""

import argparse
import os
import sys
from datetime import UTC, datetime

import numpy as np
import psycopg
from numpy.typing import NDArray

from algo.data import global_markets as g
from algo.factory.study import WINDOW
from algo.market import evaluate as ev
from algo.market import volatility as v

CUTOFF = WINDOW[1]
ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--out")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
with psycopg.connect(a.db) as conn:
    bars = conn.execute(
        "SELECT trade_date, open, high, low, close FROM index_bar_1d WHERE exchange='NSE' AND symbol='NIFTY 500' AND trade_date <= %s ORDER BY trade_date",
        (CUTOFF,),
    ).fetchall()
    vix = {
        d: float(c)
        for d, c in conn.execute(
            "SELECT trade_date, close FROM index_bar_1d WHERE exchange='NSE' AND symbol='INDIA VIX' AND trade_date <= %s",
            (CUTOFF,),
        )
    }
    sp = [r for r in g.series(conn, "SP500") if r[0] <= CUTOFF]
    vx = [r for r in g.series(conn, "VIXUS") if r[0] <= CUTOFF]
sessions = [v.Session(d, float(o), float(h), float(lo), float(c)) for d, o, h, lo, c in bars]
assert sessions[-1].day <= CUTOFF
night = {}
for s in sessions:
    r1, r2 = g.last_session_return(sp, s.day), g.last_session_return(vx, s.day)
    if r1 is not None and r2 is not None:
        night[s.day] = (r1, r2)
days, X, yr, ym = v.build(sessions, vix, night)
n = len(days)
yrs = np.array([d.year for d in days])
vix_prev = np.exp(X[:, 4])
lo_v, hi_v = np.quantile(vix_prev, [1 / 3, 2 / 3])
out = [
    f"# Volatility forecast: development-period evaluation (sessions to {CUTOFF}; the 2025 holdout is not read)\n",
    f"Made {datetime.now(UTC).date()}. {n} sessions ({days[0]} to {days[-1]}), forecast before the open from yesterday's ranges, India VIX and the US overnight. Walk-forward: refitted every {v.REFIT} sessions on earlier sessions only, first {v.MIN_TRAIN} used to fit. Ridge strength {v.ALPHA}, inputs and baselines fixed in advance. Errors are in % points of the index.\n",
]


def mae_gap(
    base: v.Arr, model: v.Arr, y: v.Arr, idx: NDArray[np.intp]
) -> tuple[float, float, float]:
    """MAE of the baseline minus MAE of the model on sessions `idx` (positive: the model has the smaller error), with a 95% block-bootstrap interval."""

    def gap(i: NDArray[np.intp]) -> float:
        return float(
            np.mean(np.abs(base[idx][i] - y[idx][i])) - np.mean(np.abs(model[idx][i] - y[idx][i]))
        )

    lo, hi = ev.block_ci(gap, len(idx), reps=2000)
    return gap(np.arange(len(idx))), lo, hi


res = {}
for tname, y, floor_name in (
    ("next-session high-low range (% of open)", yr, "range"),
    ("next-session absolute close-to-close move (%)", ym, "move"),
):
    model = v.walk_forward(X, y)
    preds = {
        "Model": model,
        "Yesterday's value": v.persistence(y),
        "Average of the last 5 sessions": v.trailing_mean(y, 5),
        "Average of the last 22 sessions": v.trailing_mean(y, 22),
        "India VIX scaled": v.scaled_vix(X, y),
    }
    ok = (
        ~np.isnan(model)
        & ~np.isnan(preds["Average of the last 22 sessions"])
        & ~np.isnan(preds["Yesterday's value"])
    )
    idx = np.flatnonzero(ok)
    res[floor_name] = (y, preds, ok)
    yday = v.persistence(y)
    out += [
        f"## {tname}\n",
        f"{int(ok.sum())} sessions scored (average actual {y[ok].mean():.3f}).\n",
        "| Forecast | MAE | RMSE | Bias (forecast minus actual) | Direction of the change right |",
        "|---|---|---|---|---|",
    ]
    for name, pr in preds.items():
        mae, rmse = v.errors(pr[ok], y[ok])
        out.append(
            f"| {name} | {mae:.4f} | {rmse:.4f} | {np.mean(pr[ok] - y[ok]):+.4f} | {v.change_direction_accuracy(pr[ok], y[ok], yday[ok]):.1%} |"
        )
    out.append("")
    for name, pr in preds.items():
        if name == "Model":
            continue
        gap, lo, hi = mae_gap(pr, model, y, idx)
        out.append(
            f"- MAE gap against **{name}** (baseline minus model): {gap:+.4f} (95% {lo:+.4f} to {hi:+.4f}), so the model is **{'better than' if lo > 0 else 'worse than' if hi < 0 else 'not distinguishable from'}** it."
        )
    out += [
        "",
        "Which inputs matter (the model refitted without a group; MAE on the same sessions):\n",
        "| Inputs | MAE |",
        "|---|---|",
    ]
    names = v.FEATURES
    groups = {
        "all inputs": [],
        "without India VIX": ["india_vix"],
        "without the US overnight": ["us_sp_size", "us_vix_change"],
        "without the recent ranges and moves": [
            "range_yesterday",
            "range_week",
            "range_month",
            "move_week",
        ],
    }
    for label, drop in groups.items():
        keep = [i for i, nm in enumerate(names) if nm not in drop]
        pr = v.walk_forward(X[:, keep], y)
        out.append(f"| {label} | {v.errors(pr[ok], y[ok])[0]:.4f} |")
    out += [
        "",
        "By India VIX regime (yesterday's close; thirds of the whole period) and by year, model against the best simple baseline (average of the last 22 sessions):\n",
        "| Segment | Sessions | Model MAE | 22-session average MAE |",
        "|---|---|---|---|",
    ]
    segs = [
        ("VIX low", vix_prev <= lo_v),
        ("VIX middle", (vix_prev > lo_v) & (vix_prev <= hi_v)),
        ("VIX high", vix_prev > hi_v),
    ] + [(str(yy), yrs == yy) for yy in sorted(set(yrs[ok].tolist()))]
    for label, mk in segs:
        m = ok & mk
        if m.sum() >= 30:
            out.append(
                f"| {label} | {int(m.sum())} | {v.errors(model[m], y[m])[0]:.4f} | {v.errors(preds['Average of the last 22 sessions'][m], y[m])[0]:.4f} |"
            )
    q = np.quantile(model[ok], np.linspace(0, 1, 6))
    out += [
        "",
        "Calibration of the level (sessions grouped by the size of the forecast):\n",
        "| Forecast group | Sessions | Average forecast | Average actual |",
        "|---|---|---|---|",
    ]
    for b in range(5):
        m = ok & (model >= q[b]) & (model <= q[b + 1] if b == 4 else model < q[b + 1])
        out.append(
            f"| fifth {b + 1} (smallest to largest) | {int(m.sum())} | {model[m].mean():.3f} | {y[m].mean():.3f} |"
        )
    out.append("")
text = "\n".join(out) + "\n"
path = a.out or f"docs/forecast/volatility_dev_{datetime.now(UTC).date()}.md"
with open(path, "w") as fh:
    fh.write(text)
print(text)
print(f"written {path}")
