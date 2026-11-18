# ruff: noqa: E501
"""Why did the morning forecast's edge fade? A DEVELOPMENT-PERIOD diagnosis only: every figure here uses days up to the development end (algo.factory.study.WINDOW[1],
2024-12-31); the global holdout (2025-01-01 on) is never read, so nothing is tuned or chosen on it. Nothing is fitted or selected: the checks are descriptive (how the US-India
link, the open versus the close, the volatility regimes, the feature distributions and the stored walk-forward probabilities behaved year by year).
usage: diagnose_forecast_edge.py [--db URL] [--out docs/forecast/diagnosis_<date>.md]"""

import argparse
import os
import sys
from datetime import UTC, date, datetime

import numpy as np
import psycopg
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]

from algo.data import global_markets as g
from algo.factory.study import WINDOW
from algo.market import evaluate as ev
from algo.market import forecast

CUTOFF: date = WINDOW[1]  # the end of development; later days are the holdout and are not touched
ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--out")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
with psycopg.connect(a.db) as conn:
    bars = conn.execute(
        "SELECT trade_date, open, close FROM index_bar_1d WHERE exchange='NSE' AND symbol='NIFTY 500' AND trade_date <= %s ORDER BY trade_date",
        (CUTOFF,),
    ).fetchall()
    vixi = {
        d: float(c)
        for d, c in conn.execute(
            "SELECT trade_date, close FROM index_bar_1d WHERE exchange='NSE' AND symbol='INDIA VIX' AND trade_date <= %s",
            (CUTOFF,),
        )
    }
    us = {
        k: [r for r in g.series(conn, s) if r[0] <= CUTOFF]
        for k, s in (("sp", "SP500"), ("nq", "NASDAQ"), ("vix", "VIXUS"))
    }
    wf = conn.execute(
        "SELECT as_of, p_up, outcome_up FROM prediction_log WHERE subject='MARKET' AND horizon_days=1 AND live=false AND model_version=%s AND outcome_up IS NOT NULL AND as_of <= %s ORDER BY as_of",
        (forecast.version("morning"), CUTOFF),
    ).fetchall()
assert (
    all(b[0] <= CUTOFF for b in bars)
    and all(r[0] <= CUTOFF for s in us.values() for r in s)
    and all(w[0] <= CUTOFF for w in wf)
)  # nothing after the development end

rows = []  # day, US returns, Nifty gap / intraday / total
for (pd_, _po, pc), (d, o, c) in zip(bars, bars[1:], strict=False):
    if float(o) <= 1 or float(pc) <= 0:
        continue
    sp, nq, vx = (g.last_session_return(us[k], d) for k in ("sp", "nq", "vix"))
    if sp is None or nq is None or vx is None:
        continue
    gap, intra, tot = (
        100 * (float(o) / float(pc) - 1),
        100 * (float(c) / float(o) - 1),
        100 * (float(c) / float(pc) - 1),
    )
    rows.append((d, sp, nq, vx, gap, intra, tot, vixi.get(pd_)))
yrs = np.array([r[0].year for r in rows])
A = np.array([[r[1], r[2], r[3], r[4], r[5], r[6]] for r in rows])
sp, nq, vx, gap, intra, tot = A.T
vind = np.array([np.nan if r[7] is None else r[7] for r in rows])
years = sorted(set(yrs.tolist()))
corr = lambda x, y: float(np.corrcoef(x, y)[0, 1])  # noqa: E731
out = [
    "# Why did the morning forecast's edge fade? Development-period diagnosis\n",
    f"Made {datetime.now(UTC).date()}. Days {rows[0][0]} to {rows[-1][0]} ({len(rows)}): **development data only** (the study window ends {CUTOFF}; the 2025-01-01 holdout is not read). Descriptive: nothing is fitted or chosen here.\n",
]

out += [
    "## 1. Does the US still drive the Indian day?\n",
    "Model-free: the S&P 500's last session against the Nifty 500 that day. `Rule` = call the day up when the S&P rose.\n",
    "| Year | Days | Corr S&P with open gap | Corr S&P with intraday move | Corr S&P with close-to-close | Beta (close-to-close per 1% S&P) | Rule accuracy | Share of days up |",
    "|---|---|---|---|---|---|---|---|",
]
for yr in years:
    m = yrs == yr
    beta = float(np.polyfit(sp[m], tot[m], 1)[0])
    rule = float(np.mean((sp[m] > 0) == (tot[m] > 0)))
    out.append(
        f"| {yr} | {int(m.sum())} | {corr(sp[m], gap[m]):+.2f} | {corr(sp[m], intra[m]):+.2f} | {corr(sp[m], tot[m]):+.2f} | {beta:+.2f} | {rule:.1%} | {np.mean(tot[m] > 0):.1%} |"
    )

out += [
    "",
    "## 2. Is the gap held or faded during the day?\n",
    "If the US-driven opening gap is increasingly reversed by the close, the close-to-close day follows the US less even though the opening still does.\n",
    "| Year | Corr (gap, intraday move) | Gap held by the close (same sign) | Average |gap| % | Average |intraday| % | Gap's share of the day's variance |",
    "|---|---|---|---|---|---|",
]
for yr in years:
    m = yrs == yr
    held = float(np.mean(np.sign(gap[m]) == np.sign(tot[m])))
    out.append(
        f"| {yr} | {corr(gap[m], intra[m]):+.2f} | {held:.1%} | {np.mean(np.abs(gap[m])):.2f} | {np.mean(np.abs(intra[m])):.2f} | {np.var(gap[m]) / np.var(tot[m]):.0%} |"
    )

out += [
    "",
    "## 3. Do the inputs behave differently?\n",
    "| Year | S&P daily std % | Share of |S&P| over 1% | US VIX change std % | Nifty 500 close-to-close std % | India VIX average |",
    "|---|---|---|---|---|---|",
]
for yr in years:
    m = yrs == yr
    out.append(
        f"| {yr} | {np.std(sp[m]):.2f} | {np.mean(np.abs(sp[m]) > 1):.0%} | {np.std(vx[m]):.1f} | {np.std(tot[m]):.2f} | {np.nanmean(vind[m]):.1f} |"
    )

lo_v, hi_v = np.nanquantile(vind, [1 / 3, 2 / 3])
out += [
    "",
    f"## 4. Volatility regimes (India VIX at the previous close; thirds at {lo_v:.1f} and {hi_v:.1f}, over the whole development period)\n",
    "| Year | Regime | Days | Corr S&P with close-to-close | Rule accuracy |",
    "|---|---|---|---|---|",
]
for yr in years:
    for name, mask in (
        ("low", vind <= lo_v),
        ("middle", (vind > lo_v) & (vind <= hi_v)),
        ("high", vind > hi_v),
    ):
        m = (yrs == yr) & mask
        if m.sum() >= 30:
            out.append(
                f"| {yr} | {name} | {int(m.sum())} | {corr(sp[m], tot[m]):+.2f} | {np.mean((sp[m] > 0) == (tot[m] > 0)):.1%} |"
            )

if wf:
    d = np.array([w[0] for w in wf])
    p = np.array([float(w[1]) for w in wf])
    y = np.array([float(w[2]) for w in wf])
    wy = np.array([x.year for x in d])
    base = ev.expanding_base(y, 1)
    out += [
        "",
        "## 5. Calibration of the stored walk-forward probabilities, by year\n",
        "Slope: 1 is calibrated; below 1 the model is overconfident (its probabilities are too far from 50%). Fitted on the year's own predictions, as a measurement only.\n",
        "| Year | Days | Average said | Actually rose | Slope | Brier skill vs usual tendency | Accuracy |",
        "|---|---|---|---|---|---|---|",
    ]
    for yr in sorted(set(wy.tolist())):
        m = wy == yr
        z = np.log(np.clip(p[m], 1e-4, 1 - 1e-4) / (1 - np.clip(p[m], 1e-4, 1 - 1e-4))).reshape(
            -1, 1
        )
        slope = (
            float(LogisticRegression(C=1e6, max_iter=500).fit(z, y[m]).coef_[0][0])
            if len(set(y[m].tolist())) > 1
            else float("nan")
        )
        out.append(
            f"| {yr} | {int(m.sum())} | {p[m].mean():.1%} | {y[m].mean():.1%} | {slope:.2f} | {ev.brier_skill(p[m], y[m], base[m]):+.4f} | {np.mean((p[m] > 0.5) == (y[m] == 1)):.1%} |"
        )

bins = ((0, 0.5, "under 0.5%"), (0.5, 1.0, "0.5 to 1%"), (1.0, 99.0, "over 1%"))
periods = (
    ("2016-19", range(2016, 2020)),
    ("2020-21", (2020, 2021)),
    ("2022-23", (2022, 2023)),
    ("2024", (2024,)),
)
out += [
    "",
    "## 6. Is it the relationship or the mix of days? Rule accuracy by the size of the US move\n",
    "If the relationship decayed, accuracy at a given US move size would fall over time; if only the mix changed, it would not.\n",
    "| S&P move | " + " | ".join(n for n, _ in periods) + " |",
    "|---|" + "---|" * len(periods),
]
for lo, hi, lab in bins:
    cells = []
    for _n, ys in periods:
        m = np.isin(yrs, list(ys)) & (np.abs(sp) >= lo) & (np.abs(sp) < hi)
        cells.append(
            f"{np.mean((sp[m] > 0) == (tot[m] > 0)):.1%} ({int(m.sum())} days)"
            if m.sum() >= 20
            else f"({int(m.sum())} days)"
        )
    out.append(f"| {lab} | " + " | ".join(cells) + " |")
out.append(
    "| *Share of days over 1%* | "
    + " | ".join(f"{np.mean((np.abs(sp) > 1)[np.isin(yrs, list(ys))]):.0%}" for _n, ys in periods)
    + " |"
)
m24, m0 = yrs == 2024, np.isin(yrs, [2020, 2021, 2022, 2023])
r24, r0 = corr(sp[m24], tot[m24]), corr(sp[m0], tot[m0])
fz = (np.arctanh(r24) - np.arctanh(r0)) / np.sqrt(1 / (m24.sum() - 3) + 1 / (m0.sum() - 3))
out += [
    "",
    f"Correlation of the S&P with the Nifty 500 close-to-close: 2024 {r24:+.2f} against 2020-2023 {r0:+.2f} (Fisher z {fz:+.1f}).\n",
]
if wf:
    out += [
        "## 7. Brier skill by year with 95% block-bootstrap intervals (stored walk-forward)\n",
        "| Year | Days | Brier skill | 95% interval |",
        "|---|---|---|---|",
    ]
    for yr in sorted(set(wy.tolist())):
        ix = np.flatnonzero(wy == yr)
        sk = lambda i, ix=ix: ev.brier_skill(p[ix][i], y[ix][i], base[ix][i])  # noqa: E731
        lo, hi = ev.block_ci(sk, len(ix), block=20, reps=1000)
        out.append(f"| {yr} | {len(ix)} | {sk(np.arange(len(ix))):+.4f} | {lo:+.4f} to {hi:+.4f} |")
    out.append("")
    rng = np.random.default_rng(3)
    skill = lambda ix: ev.brier_skill(p[ix], y[ix], base[ix])  # noqa: E731
    i24 = np.flatnonzero(wy == 2024)
    for label, yrs_ in (
        ("2020-2023", (2020, 2021, 2022, 2023)),
        ("2022-2023", (2022, 2023)),
        ("2020-2021", (2020, 2021)),
    ):
        ip = np.flatnonzero(np.isin(wy, yrs_))
        diffs = [
            skill(i24[ev.block_resample(len(i24), 20, rng)])
            - skill(ip[ev.block_resample(len(ip), 20, rng)])
            for _ in range(1000)
        ]
        out.append(
            f"- 2024 minus {label}: {skill(i24) - skill(ip):+.4f} (95% {np.quantile(diffs, 0.025):+.4f} to {np.quantile(diffs, 0.975):+.4f})"
        )

text = "\n".join(out) + "\n"
path = a.out or f"docs/forecast/diagnosis_{datetime.now(UTC).date()}.md"
with open(path, "w") as fh:
    fh.write(text)
print(text)
print(f"written {path}")
