# ruff: noqa: E501
"""Are the fills the hold-until-sell-signal study assumes realistic? Development period only (2022-2024 trades from study_hold_signal_folds.py --dump); 2025-01-01 onward is never read.

The study buys/sells at the NEXT session's open price (the daily bar's open) and charges the repo's cost model: DB charges + slippage of 5 bps + 5 bps per 1% of the bar's volume, per side.
This script takes a random sample of the study's entries and exits and looks at the first 5 minutes of that session in the Kite 1-minute bars:
  - does the first minute print the daily open (data consistency)?
  - what would a market order sent at 09:15 have paid, against the open? (volume-weighted price of the first 5 minutes, in bps, positive = against us)
  - how big is the order (Rs 20,000) against the first minutes' volume (can it fill at all)?
  - how many sessions show no trading range in the first 5 minutes (locked at a circuit limit, or no prints), where a buy at the open might not execute?
Then the study's net return is restated with the measured slippage in place of the modelled one.
usage: check_execution_assumptions.py [--db URL] [--trades CSV] [--n 1500] [--order-value 20000]"""

import argparse
import os
import sys
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import psycopg
from winner_v2_common import DEV_END, ROOT

IST = ZoneInfo("Asia/Kolkata")
ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--trades", default=str(ROOT / "data/research/winner_v2/dev_trades_from2016.csv"))
ap.add_argument("--n", type=int, default=1500)
ap.add_argument("--order-value", type=float, default=20000.0)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
t = pd.read_csv(a.trades, parse_dates=["exec_date", "exit_exec_date"])
assert t["exit_exec_date"].max() <= pd.Timestamp(DEV_END) + pd.Timedelta(days=5), (
    "trades must be development-period only"
)
buys = t.sample(min(a.n, len(t)), random_state=0)
sells = t.sample(min(a.n, len(t)), random_state=1)
legs = pd.concat(
    [
        pd.DataFrame(
            {"iid": buys["iid"], "side": "BUY", "day": buys["exec_date"], "price": buys["pe"]}
        ),
        pd.DataFrame(
            {
                "iid": sells["iid"],
                "side": "SELL",
                "day": sells["exit_exec_date"],
                "price": sells["px"],
            }
        ),
    ]
).reset_index(drop=True)
print(
    f"{len(t):,} development trades; checking {len(legs):,} sampled fills (half buys, half sells) against the first 5 minutes of 1-minute bars; order Rs {a.order_value:,.0f}"
)

recs: list[dict[str, Any]] = []
with psycopg.connect(a.db) as conn:
    for day, g in legs.groupby("day"):
        d0 = datetime.combine(day.date(), time(9, 15), tzinfo=IST)
        got = conn.execute(
            "SELECT DISTINCT ON (instrument_id, ts) instrument_id, ts, open::float8, high::float8, low::float8, close::float8, volume::float8 FROM bar_1m"
            " WHERE source='kite' AND instrument_id = ANY(%s) AND ts >= %s AND ts < %s ORDER BY instrument_id, ts, dataset_version DESC",
            (g["iid"].astype(int).tolist(), d0, d0 + timedelta(minutes=5)),
        ).fetchall()
        mb = pd.DataFrame(got, columns=["iid", "ts", "o", "h", "l", "c", "v"])
        by = dict(tuple(mb.groupby("iid"))) if len(mb) else {}
        for r in g.itertuples():
            m = by.get(int(r.iid))
            rec: dict[str, Any] = {
                "side": r.side,
                "price": r.price,
                "missing": m is None or float(m["v"].sum()) <= 0,
            }
            if not rec["missing"]:
                vwap = float((m["c"] * m["v"]).sum() / m["v"].sum())
                rec.update(
                    m1_open=float(m["o"].iloc[0]),
                    slip=(vwap / r.price - 1) if r.side == "BUY" else (1 - vwap / r.price),
                    part5=(a.order_value / r.price) / float(m["v"].sum()),
                    range5=float(m["h"].max() - m["l"].min()) / r.price,
                )
            recs.append(rec)
d = pd.DataFrame(recs)
ok = d[~d["missing"]].copy()
print(
    f"minute bars with trades found for {len(ok):,} of {len(d):,} sampled fills ({100 * len(ok) / len(d):.0f}%); the rest have no prints in the first 5 minutes"
)
print(
    f"the first minute opens at the daily open (within 0.05%): {100 * (abs(ok['m1_open'] / ok['price'] - 1) < 0.0005).mean():.1f}% of fills\n"
)
print(
    f"{'':<6}{'n':>6}{'mean bps':>10}{'median':>8}{'p90':>8}{'p99':>8}{'> 25 bps':>10}{'order / 5-min volume: median, p99':>36}{'no range in 5 min':>20}"
)
for s in ("BUY", "SELL"):
    x = ok[ok["side"] == s]
    sl = 1e4 * x["slip"]
    print(
        f"{s:<6}{len(x):>6,}{sl.mean():>10.1f}{sl.median():>8.1f}{sl.quantile(0.9):>8.1f}{sl.quantile(0.99):>8.1f}{100 * (sl > 25).mean():>9.0f}%{100 * x['part5'].median():>20.2f}% , {100 * x['part5'].quantile(0.99):>6.1f}%{100 * (x['range5'] < 1e-9).mean():>19.1f}%"
    )
modelled = (
    2 * 5.0
)  # bps: base slippage both sides (the participation term is about 0 at this order size)
measured = 1e4 * (
    ok.loc[ok["side"] == "BUY", "slip"].mean() + ok.loc[ok["side"] == "SELL", "slip"].mean()
)
print(
    f"\nround-trip slippage: modelled {modelled:.1f} bps (5 per side; participation ~0 at this size); a market order at 09:15 measured {measured:.1f} bps"
)
net_m = (t["net"] - t["mkt"]).mean()
adj = net_m - (measured - modelled) / 1e4
print(
    f"net-market per trade (2022-24 development trades): as modelled {100 * net_m:+.2f}% -> with the measured 09:15 slippage {100 * adj:+.2f}%  (mean hold {t['hold'].mean():.1f} sessions, cost model {100 * t['cost'].mean():.2f}% per round trip)"
)
print(
    "Reading it: if a 09:15 market order costs about what the model assumes, 'next open' is a fair fill. A gap between the two is what the strategy loses by not using the pre-open session."
)
print(
    "Not checked here (needs live fills): the pre-open auction fill itself, partial fills, price bands set after the signal, and orders moving a thin stock. Paper-cycle fills measure those (policy v3 section 8.1 item 4)."
)
