# ruff: noqa: E501
"""Evaluate the market forecast products on identical days and write a report: metrics, references, calibration, regimes and confidence intervals.
usage: evaluate_forecast.py [--db URL] [--horizon 1] [--out docs/forecast/evaluation_<date>.md] [--reps 1000]
Reads the stored walk-forward predictions (prediction_log, live = false) of the night and morning products. Nothing is fitted here."""

import argparse
import os
import sys
from datetime import UTC, datetime

import numpy as np
import psycopg

from algo.market import evaluate as ev
from algo.market import forecast

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--horizon", type=int, default=1)
ap.add_argument("--reps", type=int, default=1000)
ap.add_argument("--out")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
h = a.horizon
today = datetime.now(UTC).date()
with psycopg.connect(a.db) as conn:
    preds = {}
    for product in forecast.PRODUCTS:
        rows = conn.execute(
            "SELECT as_of, p_up, outcome_up FROM prediction_log WHERE subject='MARKET' AND horizon_days=%s AND live=false AND model_version=%s AND outcome_up IS NOT NULL ORDER BY as_of",
            (h, forecast.version(product)),
        ).fetchall()
        preds[product] = {r[0]: (float(r[1]), float(r[2])) for r in rows}
    closes = [
        (d, float(c))
        for d, c in conn.execute(
            "SELECT trade_date, close FROM index_bar_1d WHERE exchange='NSE' AND symbol='NIFTY 500' ORDER BY trade_date"
        )
    ]
    regime = {
        r[0]: r[1:]
        for r in conn.execute("SELECT day, trend, volatility, label FROM market_regime_daily")
    }

days = sorted(set(preds["night"]) & set(preds["morning"]))  # identical days for every model
if not days:
    sys.exit("no days in common: run build_predictions.py --backfill")
y = np.array([preds["night"][d][1] for d in days])
p = {q: np.array([preds[q][d][0] for d in days]) for q in forecast.PRODUCTS}
px = dict(closes)
order = [d for d, _ in closes]
pos = {d: i for i, d in enumerate(order)}


def ret(d, n):
    i = pos.get(d)
    return None if i is None or i < n else px[order[i]] / px[order[i - n]] - 1


rise_yday = np.array([(ret(d, 1) or 0) > 0 for d in days])
trend21 = np.array([(ret(d, 21) or 0) > 0 for d in days])
refs = {
    "Usual tendency (share of up days known so far)": ev.expanding_base(y, h),
    "Yesterday's direction": ev.expanding_conditional(rise_yday, y, h),
    "21-day momentum": ev.expanding_conditional(trend21, y, h),
    "Night model (no overnight inputs)": p["night"],
}
base = refs["Usual tendency (share of up days known so far)"]
n = len(days)
out = [
    f"# Forecast evaluation: market, {h}-day, walk-forward\n",
    f"Made {today}. {n} days, {days[0]} to {days[-1]}; every model is scored on exactly these days. {int(y.sum())} rose, {int(n - y.sum())} did not.\n",
    "Intervals are 95%, from a moving-block bootstrap (blocks of 20 days), because neighbouring days are not independent.\n",
    "## Scores\n",
    "| Model | Accuracy | Brier | Brier skill vs usual tendency | Log loss | AUC | Precision | Recall |",
    "|---|---|---|---|---|---|---|---|",
]
models = {"Morning model (with the US close)": p["morning"], **refs}
for name, pr in models.items():
    m = ev.metrics(pr, y)
    bs = ev.brier_skill(pr, y, base)
    f = lambda v: "–" if v is None else f"{v:.3f}"  # noqa: E731
    out.append(
        f"| {name} | {m.accuracy:.1%} | {m.brier:.4f} | {bs:+.4f} | {m.log_loss:.4f} | {f(m.auc)} | {f(m.precision)} | {f(m.recall)} |"
    )
m = ev.metrics(p["morning"], y)
out += [
    "",
    f"Morning model confusion matrix (called up / called down against rose / did not): TP {m.tp}, FP {m.fp}, FN {m.fn}, TN {m.tn}.\n",
    "## Is the morning model better than the references?\n",
]
for name, pr in refs.items():
    d = lambda idx, pr=pr: ev.brier(pr[idx], y[idx]) - ev.brier(p["morning"][idx], y[idx])  # noqa: E731  (positive: the morning model is better)
    lo, hi = ev.block_ci(d, n, reps=a.reps)
    verdict = "better" if lo > 0 else "worse" if hi < 0 else "not distinguishable from"
    out.append(
        f"- Against **{name}**: Brier gap {d(np.arange(n)):+.4f} (95% {lo:+.4f} to {hi:+.4f}), so the morning model is **{verdict}** it."
    )
acc = lambda idx: float(np.mean((p["morning"][idx] > 0.5) == (y[idx] == 1)))  # noqa: E731
lo, hi = ev.block_ci(acc, n, reps=a.reps)
bss = lambda idx: ev.brier_skill(p["morning"][idx], y[idx], base[idx])  # noqa: E731
blo, bhi = ev.block_ci(bss, n, reps=a.reps)
out += [
    "",
    f"Morning accuracy {ev.metrics(p['morning'], y).accuracy:.1%} (95% {lo:.1%} to {hi:.1%}); Brier skill vs the usual tendency {bss(np.arange(n)):+.4f} (95% {blo:+.4f} to {bhi:+.4f}).\n",
    "## Calibration (morning model)\n",
    "| Said | Days | Average said | Actually rose |",
    "|---|---|---|---|",
]
out += [
    f"| {c['from']:.0%} to {min(c['to'], 1):.0%} | {c['n']} | {c['said']:.1%} | {c['actual']:.1%} |"
    for c in ev.calibration(p["morning"], y)
]
for title, idx in (("Trend", 0), ("Volatility", 1), ("Market zone", 2)):
    labels = [str((regime.get(d) or (None, None, None))[idx] or "unknown") for d in days]
    seg = ev.by_segment(labels, p["morning"], y, base)
    out += [
        "",
        f"## By {title.lower()} (morning model)\n",
        "| Segment | Days | Accuracy | Brier skill | Share that rose |",
        "|---|---|---|---|---|",
    ]
    out += [
        f"| {k} | {v['n']} | {v['accuracy']:.1%} | {v['brier_skill']:+.4f} | {v['base_rate']:.1%} |"
        for k, v in seg.items()
    ]
years = np.array([d.year for d in days])
out += [
    "",
    "## By year (morning model)\n",
    "| Year | Days | Accuracy | Brier skill |",
    "|---|---|---|---|",
]
for yr in sorted(set(years.tolist())):
    mk = years == yr
    out.append(
        f"| {yr} | {int(mk.sum())} | {np.mean((p['morning'][mk] > 0.5) == (y[mk] == 1)):.1%} | {ev.brier_skill(p['morning'][mk], y[mk], base[mk]):+.4f} |"
    )
text = "\n".join(out) + "\n"
path = a.out or f"docs/forecast/evaluation_{today}_h{h}.md"
with open(path, "w") as fh:
    fh.write(text)
print(text)
print(f"written {path}")
