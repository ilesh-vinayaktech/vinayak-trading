# ruff: noqa: E501
"""Step 1 of the improvement plan, a DEVELOPMENT-PERIOD test (days up to algo.factory.study.WINDOW[1]; the 2025 holdout is never read): does calibrating the morning model's
probabilities, and abstaining when the US moved little, help? Two choices, fixed before looking:
  * calibration: Platt scaling (one slope and one intercept on the log-odds), fitted on EARLIER stored walk-forward predictions whose outcomes were already known, refitted every 21
    days, from 250 predictions on. No other method is tried.
  * abstain: no call when the S&P 500's last session moved less than 0.5% either way (the size bin that carried no information in the diagnosis). No other threshold is tried.
Both are evaluated on the same days as the unchanged model, with block-bootstrap intervals. Nothing here changes production or is shown on the page.
usage: evaluate_calibration_abstain.py [--db URL] [--out docs/forecast/calibration_abstain_<date>.md]"""

import argparse
import os
import sys
from datetime import UTC, datetime

import numpy as np
import psycopg
from numpy.typing import NDArray
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]

from algo.factory.study import WINDOW
from algo.market import evaluate as ev
from algo.market import forecast

CUTOFF = WINDOW[1]
MIN_CAL, REFIT, ABSTAIN_BELOW = 250, 21, 0.5
ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--out")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
with psycopg.connect(a.db) as conn:
    rows = conn.execute(
        "SELECT as_of, p_up, outcome_up, (features->>'us_sp')::float8 FROM prediction_log WHERE subject='MARKET' AND horizon_days=1 AND live=false AND model_version=%s"
        " AND outcome_up IS NOT NULL AND as_of <= %s AND features ? 'us_sp' ORDER BY as_of",
        (forecast.version("morning"), CUTOFF),
    ).fetchall()
assert all(r[0] <= CUTOFF for r in rows)
d = np.array([r[0] for r in rows])
p = np.array([float(r[1]) for r in rows])
y = np.array([float(r[2]) for r in rows])
us = np.array([float(r[3]) for r in rows])
n = len(y)


def lg(q: NDArray[np.float64]) -> NDArray[np.float64]:
    c = np.clip(q, 1e-4, 1 - 1e-4)
    return np.asarray(np.log(c / (1 - c)))


def platt(upto: int) -> tuple[float, float]:
    """Slope and intercept fitted on the predictions of days before `upto` (their outcomes are known by then: the horizon is one day)."""
    m = LogisticRegression(C=1e6, max_iter=500).fit(lg(p[:upto]).reshape(-1, 1), y[:upto])
    return float(m.coef_[0][0]), float(m.intercept_[0])


pc = np.full(n, np.nan)
for start in range(MIN_CAL, n, REFIT):
    b, a0 = platt(start)
    end = min(start + REFIT, n)
    pc[start:end] = 1 / (1 + np.exp(-(a0 + b * lg(p[start:end]))))
ok = ~np.isnan(pc)
D, P, PC, Y, US = d[ok], p[ok], pc[ok], y[ok], us[ok]
m_ = len(Y)
ref = ev.expanding_base(Y, 1)
years = np.array([x.year for x in D])
out = [
    f"# Calibration and abstaining: development-period test (days to {CUTOFF}; the 2025 holdout is not read)\n",
    f"Made {datetime.now(UTC).date()}. The morning model's stored walk-forward predictions, {m_} days ({D[0]} to {D[-1]}), the first {MIN_CAL} used only to fit the calibrator. Two choices fixed in advance: Platt scaling refitted every {REFIT} days on earlier predictions with known outcomes, and no call when the S&P 500 moved under {ABSTAIN_BELOW}%.\n",
]

out += [
    "## 1. Calibration\n",
    "| | Brier | Brier skill vs usual tendency | Log loss | Accuracy | Calibration slope |",
    "|---|---|---|---|---|---|",
]
for name, q in (("Unchanged", P), ("Calibrated", PC)):
    mm = ev.metrics(q, Y)
    slope = float(LogisticRegression(C=1e6, max_iter=500).fit(lg(q).reshape(-1, 1), Y).coef_[0][0])
    out.append(
        f"| {name} | {mm.brier:.4f} | {ev.brier_skill(q, Y, ref):+.4f} | {mm.log_loss:.4f} | {mm.accuracy:.1%} | {slope:.2f} |"
    )


def gap(i: NDArray[np.intp]) -> float:
    return ev.brier(P[i], Y[i]) - ev.brier(PC[i], Y[i])


lo, hi = ev.block_ci(gap, m_, reps=2000)
out += [
    f"\nBrier gap (unchanged minus calibrated, positive means calibration helps): {gap(np.arange(m_)):+.5f} (95% {lo:+.5f} to {hi:+.5f}).\n",
    "Calibration table, unchanged against calibrated:\n",
    "| Said | Days | Said (unchanged) | Rose | Said (calibrated) | Rose |",
    "|---|---|---|---|---|---|",
]
for c0, c1 in zip(ev.calibration(P, Y), ev.calibration(PC, Y), strict=False):
    out.append(
        f"| {c0['from']:.0%} to {min(c0['to'], 1):.0%} | {c0['n']} | {c0['said']:.1%} | {c0['actual']:.1%} | {c1['said']:.1%} ({c1['n']} days) | {c1['actual']:.1%} |"
    )

called = np.abs(US) >= ABSTAIN_BELOW
out += [
    "",
    f"## 2. Abstaining when the S&P moved under {ABSTAIN_BELOW}%\n",
    f"Called on {int(called.sum())} of {m_} days ({called.mean():.0%}); no call on {int((~called).sum())}.\n",
    "| Days | Count | Accuracy | Brier skill vs usual tendency | Share that rose |",
    "|---|---|---|---|---|",
]
for name, mk in (
    ("All days", np.ones(m_, bool)),
    ("Called (S&P moved at least 0.5%)", called),
    ("No call (S&P moved under 0.5%)", ~called),
):
    out.append(
        f"| {name} | {int(mk.sum())} | {np.mean((P[mk] > 0.5) == (Y[mk] == 1)):.1%} | {ev.brier_skill(P[mk], Y[mk], ref[mk]):+.4f} | {Y[mk].mean():.1%} |"
    )


def acc(i: NDArray[np.intp]) -> float:
    return float(np.mean((P[called][i] > 0.5) == (Y[called][i] == 1)))


alo, ahi = ev.block_ci(acc, int(called.sum()), reps=2000)
rng = np.random.default_rng(11)
ia, ib = np.flatnonzero(called), np.flatnonzero(~called)
diffs = []
for _ in range(2000):
    xa, xb = ia[ev.block_resample(len(ia), 20, rng)], ib[ev.block_resample(len(ib), 20, rng)]
    diffs.append(np.mean((P[xa] > 0.5) == (Y[xa] == 1)) - np.mean((P[xb] > 0.5) == (Y[xb] == 1)))
out += [
    f"\nAccuracy on called days {acc(np.arange(int(called.sum()))):.1%} (95% {alo:.1%} to {ahi:.1%}); called minus no-call accuracy {np.mean((P[ia] > 0.5) == (Y[ia] == 1)) - np.mean((P[ib] > 0.5) == (Y[ib] == 1)):+.1%} (95% {np.quantile(diffs, 0.025):+.1%} to {np.quantile(diffs, 0.975):+.1%}).\n",
    "Stable over time? (called against no-call days, by period)\n",
    "| Period | Called days | Accuracy called | No-call days | Accuracy no-call |",
    "|---|---|---|---|---|",
]
for lab, ys in (("2020-2021", (2020, 2021)), ("2022-2023", (2022, 2023)), ("2024", (2024,))):
    pm = np.isin(years, ys)
    c, nc = pm & called, pm & ~called
    out.append(
        f"| {lab} | {int(c.sum())} | {np.mean((P[c] > 0.5) == (Y[c] == 1)):.1%} | {int(nc.sum())} | {np.mean((P[nc] > 0.5) == (Y[nc] == 1)):.1%} |"
    )
cc = called
out += [
    "",
    "## 3. Both together (calibrated probabilities, called days only)\n",
    f"Accuracy {np.mean((PC[cc] > 0.5) == (Y[cc] == 1)):.1%}, Brier skill vs usual tendency {ev.brier_skill(PC[cc], Y[cc], ref[cc]):+.4f}, on {int(cc.sum())} days; the unchanged model on the same days: accuracy {np.mean((P[cc] > 0.5) == (Y[cc] == 1)):.1%}, Brier skill {ev.brier_skill(P[cc], Y[cc], ref[cc]):+.4f}.\n",
]
text = "\n".join(out) + "\n"
path = a.out or f"docs/forecast/calibration_abstain_{datetime.now(UTC).date()}.md"
open(path, "w").write(text)
print(text)
print(f"written {path}")
