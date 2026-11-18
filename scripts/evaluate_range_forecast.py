# ruff: noqa: E501
"""The ONE forward evaluation of the expected-range forecast range-ridge-v1 (docs/forecast/volatility_v1_spec.md, section 7).
usage: evaluate_range_forecast.py [--db URL]
Eligible: live forecasts made after the freeze time and before 09:15 IST of the session they forecast, with the actual range known. Below 500 eligible sessions it prints only the count and exits.
At 500 or more it runs the frozen test (MAE of the 5-session-average baseline minus the model's, paired block bootstrap, lower 95% bound above zero), writes the report and refuses to run again.
Nothing is fitted here; the baselines are computed from the stored candles using only earlier sessions."""

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import psycopg

from algo.market import range_evaluate as re
from algo.market import range_forecast as rf
from algo.market import volatility as v

REPORT = Path("docs/forecast/volatility_v1_primary_evaluation.md")
FREEZE = json.loads(Path("docs/forecast/volatility_v1_freeze.json").read_text())
FROZEN_AT = datetime.fromisoformat(FREEZE["frozen_at"])
CHANGED = [
    f for f, h in FREEZE["sha256"].items() if hashlib.sha256(Path(f).read_bytes()).hexdigest() != h
]
IST = ZoneInfo("Asia/Kolkata")
VIX_CUTS = (13.9, 17.2)  # fixed from the development period

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
if REPORT.exists():
    sys.exit(f"the primary evaluation was already run ({REPORT}); it is not repeated")
with psycopg.connect(a.db) as conn:
    rows = conn.execute(
        "SELECT as_of, made_at, forecast_range, features, target_day, actual_range FROM range_forecast_log WHERE model_version=%s ORDER BY as_of",
        (rf.VERSION,),
    ).fetchall()
    sessions = rf._sessions(conn, datetime.now(UTC).date())
    from algo.data import global_markets as g

    vix = {
        d: float(c)
        for d, c in conn.execute(
            "SELECT trade_date, close FROM index_bar_1d WHERE exchange='NSE' AND symbol='INDIA VIX'"
        )
    }
    sp, vx = g.series(conn, "SP500"), g.series(conn, "VIXUS")
eligible = [
    r
    for r in rows
    if r[5] is not None
    and r[4] is not None
    and r[1] >= FROZEN_AT
    and r[1].astimezone(IST) < datetime.combine(r[4], time(9, 15), IST)
]
print(
    f"eligible forward sessions: {len(eligible)} (needed {re.MIN_SESSIONS}); forecasts made: {len(rows)}; not eligible or not yet resolved: {len(rows) - len(eligible)}"
)
if CHANGED:
    print(f"WARNING: these frozen files differ from the freeze record: {', '.join(CHANGED)}")
if len(eligible) < re.MIN_SESSIONS:
    sys.exit(0)  # nothing is computed before the frozen endpoint
rng_by_day = {s.day: v.range_pct(s) for s in sessions}
order = [s.day for s in sessions]
pos = {d: i for i, d in enumerate(order)}
night = {}
for s in sessions:
    a1, b1 = g.last_session_return(sp, s.day), g.last_session_return(vx, s.day)
    if a1 is not None and b1 is not None:
        night[s.day] = (a1, b1)
days, X, yr, _ = v.build(sessions, vix, night)
vscaled = dict(zip(days, v.scaled_vix(X, yr), strict=True))
y = np.array([float(r[5]) for r in eligible])
model = np.array([float(r[2]) for r in eligible])
asof = [pos[r[0]] for r in eligible]
base = {
    "Average of the last 5 sessions": np.array(
        [np.mean([rng_by_day[order[i - k]] for k in range(5)]) for i in asof]
    ),
    "Average of the last 22 sessions": np.array(
        [np.mean([rng_by_day[order[i - k]] for k in range(22)]) for i in asof]
    ),
    "Yesterday's range": np.array([rng_by_day[order[i]] for i in asof]),
    "India VIX scaled": np.array([vscaled.get(r[4], np.nan) for r in eligible]),
}
res = re.primary_test(base["Average of the last 5 sessions"], model, y)
out = [
    "# range-ridge-v1: the primary forward evaluation (run once)\n",
    f"Run {datetime.now(UTC).date()}. {len(eligible)} eligible forward sessions, {eligible[0][4]} to {eligible[-1][4]}; {len(rows) - len(eligible)} forecasts not eligible or unresolved. Frozen {FREEZE['frozen_at']}; frozen files changed since: {', '.join(CHANGED) or 'none'}.\n",
    "## Primary test\n",
    "MAE of the 5-session-average baseline minus MAE of the model on the same sessions (positive favours the model); paired moving-block bootstrap (blocks of 20, 10,000 draws), two-sided 95%.\n",
    f"- Gap {res['delta']:+.5f} (% points of the open), 95% interval {res['low']:+.5f} to {res['high']:+.5f}",
    f"- **Decision: {'the lower bound is above zero: forward-validated (using it for anything still needs the owner approval)' if res['validated'] else 'the lower bound is not above zero: NOT validated'}**\n",
    "## Alongside (descriptive, not tests)\n",
    "| Forecast | MAE | RMSE | Bias (forecast minus actual) |",
    "|---|---|---|---|",
]
for name, pr in {"Model": model, **base}.items():
    ok = ~np.isnan(pr)
    mae, rmse = v.errors(pr[ok], y[ok])
    out.append(f"| {name} | {mae:.4f} | {rmse:.4f} | {np.mean(pr[ok] - y[ok]):+.4f} |")
out.append("")
for name, pr in base.items():
    ok = ~np.isnan(pr)
    gap, lo, hi = re.mae_gap(pr[ok], model[ok], y[ok], reps=2000)
    out.append(f"- MAE gap against {name}: {gap:+.4f} (95% {lo:+.4f} to {hi:+.4f})")
q = np.quantile(model, np.linspace(0, 1, 6))
out += [
    "",
    "Calibration of the level (sessions grouped by the size of the forecast):\n",
    "| Forecast group | Sessions | Average forecast | Average actual |",
    "|---|---|---|---|",
]
for b in range(5):
    m = (model >= q[b]) & ((model <= q[b + 1]) if b == 4 else (model < q[b + 1]))
    out.append(f"| fifth {b + 1} | {int(m.sum())} | {model[m].mean():.3f} | {y[m].mean():.3f} |")
vix_now = [float(np.exp(r[3]["india_vix"])) for r in eligible]
labels = [
    "VIX low" if x_ <= VIX_CUTS[0] else "VIX middle" if x_ <= VIX_CUTS[1] else "VIX high"
    for x_ in vix_now
]
halves = [f"{r[4].year} H{1 if r[4].month <= 6 else 2}" for r in eligible]
for title, lab in (
    ("India VIX regime (cut points 13.9 and 17.2, fixed from the development period)", labels),
    ("calendar half-year", halves),
):
    out += [
        "",
        f"By {title}:\n",
        "| Segment | Sessions | Model MAE | 5-session average MAE |",
        "|---|---|---|---|",
    ]
    for k, (n_, m1, m2) in re.segment_mae(
        lab, model, base["Average of the last 5 sessions"], y
    ).items():
        out.append(f"| {k} | {n_} | {m1:.4f} | {m2:.4f} |")
REPORT.write_text("\n".join(out) + "\n")
print("\n".join(out))
print(f"written {REPORT}")
