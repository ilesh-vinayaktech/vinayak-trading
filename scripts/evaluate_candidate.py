# ruff: noqa: E501
"""The ONE primary evaluation of the frozen candidate morning7 against the production morning model (docs/forecast/candidate_morning7_spec.md).
usage: evaluate_candidate.py [--db URL]
Eligible days: live predictions of both models for the market, 1 day, made from the same run before the open of the session they forecast, for sessions from the
evaluation start on, with the outcome known. Below 500 paired days it prints only the count and exits. At 500 or more it runs the frozen paired test once, writes the
report and refuses to run again (a repeated look at a growing sample is not allowed). Nothing is fitted here."""

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import psycopg
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]

from algo.market import evaluate as ev
from algo.market import forecast

START = date(
    2026, 11, 19
)  # the first session a counted prediction may forecast (the spec's evaluation start)
REPORT = Path("docs/forecast/candidate_morning7_primary_evaluation.md")
FREEZE = json.loads(Path("docs/forecast/candidate_morning7_freeze.json").read_text())
FROZEN_AT = datetime.fromisoformat(FREEZE["frozen_at"])
CHANGED = [
    f for f, h in FREEZE["sha256"].items() if hashlib.sha256(Path(f).read_bytes()).hexdigest() != h
]  # files that differ from what was frozen
IST = ZoneInfo("Asia/Kolkata")
OPEN = time(9, 15)

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
if REPORT.exists():
    sys.exit(f"the primary evaluation was already run ({REPORT}); it is not repeated")
with psycopg.connect(a.db) as conn:
    got: dict[str, dict[date, tuple[float, float, datetime, date]]] = {}
    for product in ("morning", "morning7"):
        rows = conn.execute(
            "SELECT as_of, p_up, outcome_up, made_at, resolved_on FROM prediction_log WHERE subject='MARKET' AND horizon_days=1 AND live AND model_version=%s AND outcome_up IS NOT NULL AND made_at IS NOT NULL",
            (forecast.version(product),),
        ).fetchall()
        got[product] = {
            r[0]: (float(r[1]), float(r[2]), r[3], r[4])
            for r in rows
            if r[4] >= START and r[3].astimezone(IST) < datetime.combine(r[4], OPEN, IST)
        }
    closes = [
        float(c)
        for (c,) in conn.execute(
            "SELECT close FROM index_bar_1d WHERE exchange='NSE' AND symbol='NIFTY 500' ORDER BY trade_date"
        )
    ]
    dates = [
        d
        for (d,) in conn.execute(
            "SELECT trade_date FROM index_bar_1d WHERE exchange='NSE' AND symbol='NIFTY 500' ORDER BY trade_date"
        )
    ]
    regime = {
        r[0]: r[1:]
        for r in conn.execute("SELECT day, trend, volatility, label FROM market_regime_daily")
    }
days = sorted(set(got["morning"]) & set(got["morning7"]))
unpaired = len(set(got["morning"]) ^ set(got["morning7"]))
print(
    f"paired forward days: {len(days)} (needed {ev.MIN_PAIRS}); unpaired eligible predictions: {unpaired}"
)
if len(days) < ev.MIN_PAIRS:
    sys.exit(0)  # nothing is computed before the frozen endpoint
y = np.array([got["morning"][d][1] for d in days])
p0 = np.array([got["morning"][d][0] for d in days])
p7 = np.array([got["morning7"][d][0] for d in days])
res = ev.primary_test(p0, p7, y)
pos = {d: i for i, d in enumerate(dates)}
ref = np.array(
    [
        float(np.mean([closes[j + 1] > closes[j] for j in range(pos[d])]))
        if pos.get(d, 0) > 30
        else 0.5
        for d in days
    ]
)  # the usual tendency known on each day
out = [
    "# Candidate morning7 against production: the primary evaluation (run once)\n",
    f"Run {datetime.now(UTC).date()}. {len(days)} paired forward days, {days[0]} to {days[-1]}; {unpaired} eligible predictions unpaired. Frozen {FREEZE['frozen_at']}; frozen files changed since: {', '.join(CHANGED) or 'none'}.\n",
    "## Primary test\n",
    "Delta = Brier(production morning, 18 features) - Brier(candidate morning7, 7 features); positive favours the candidate. Paired moving-block bootstrap (blocks of 20 days, 10,000 draws), two-sided 95%.\n",
    f"- Delta {res['delta']:+.5f}, 95% interval {res['low']:+.5f} to {res['high']:+.5f}",
    f"- **Decision: {'the lower bound is above zero: the candidate may be PROPOSED for promotion (owner approval is still required)' if res['promote'] else 'the lower bound is not above zero: DO NOT PROMOTE'}**\n",
    "## Diagnostics (explain the result; they are not promotion tests)\n",
    "| Model | Accuracy | Brier | Brier skill vs usual tendency | Log loss | AUC | Calibration slope |",
    "|---|---|---|---|---|---|---|",
]
for name, p in (("Production morning (18)", p0), ("Candidate morning7 (7)", p7)):
    m = ev.metrics(p, y)
    z = np.log(np.clip(p, 1e-4, 1 - 1e-4) / (1 - np.clip(p, 1e-4, 1 - 1e-4))).reshape(-1, 1)
    slope = (
        float(LogisticRegression(C=1e6, max_iter=500).fit(z, y).coef_[0][0])
        if 0 < y.sum() < len(y)
        else float("nan")
    )
    out.append(
        f"| {name} | {m.accuracy:.1%} | {m.brier:.4f} | {ev.brier_skill(p, y, ref):+.4f} | {m.log_loss:.4f} | {m.auc if m.auc is None else round(m.auc, 3)} | {slope:.2f} |"
    )
for name, p in (("Production morning (18)", p0), ("Candidate morning7 (7)", p7)):
    out += [
        "",
        f"Calibration, {name}:\n",
        "| Said | Days | Average said | Actually rose |",
        "|---|---|---|---|",
    ]
    out += [
        f"| {c['from']:.0%} to {min(c['to'], 1):.0%} | {c['n']} | {c['said']:.1%} | {c['actual']:.1%} |"
        for c in ev.calibration(p, y)
    ]
for title, idx in (("trend", 0), ("volatility", 1)):
    labels = [str((regime.get(d) or (None, None, None))[idx] or "unknown") for d in days]
    out += [
        "",
        f"By {title} (days, accuracy and Brier of each model):\n",
        "| Segment | Days | Production accuracy | Candidate accuracy | Production Brier | Candidate Brier |",
        "|---|---|---|---|---|---|",
    ]
    for seg in sorted(set(labels)):
        mk = np.array([lab == seg for lab in labels])
        if mk.sum() >= 30:
            out.append(
                f"| {seg} | {int(mk.sum())} | {np.mean((p0[mk] > 0.5) == (y[mk] == 1)):.1%} | {np.mean((p7[mk] > 0.5) == (y[mk] == 1)):.1%} | {ev.brier(p0[mk], y[mk]):.4f} | {ev.brier(p7[mk], y[mk]):.4f} |"
            )
REPORT.write_text("\n".join(out) + "\n")
print("\n".join(out))
print(f"written {REPORT}")
