# ruff: noqa: E501
"""Replay the fills of stored backtest runs under two cost-schedule folders and compare what the costs would have been. READ-ONLY: it re-prices the
SAME fills (same days, scrips, sides, quantities, prices), so trade counts cannot differ; it does not re-run strategies and writes nothing to the
database. The OLD replay must reproduce each stored cost, which proves the replay is faithful before the NEW one is believed.
usage: compare_cost_schedules.py --db ... --old DIR --new DIR [--from 2020-10-01] [--out docs/stage4/cost/cost_comparison.csv]"""

import argparse
import csv
import os
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg

from algo.backtest.costs.calculator import compute_charges
from algo.backtest.costs.schedule import ScheduleBook, load_schedules

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--old", type=Path, required=True)
ap.add_argument("--new", type=Path, required=True)
ap.add_argument(
    "--from",
    dest="start",
    default="2020-10-01",
    help="also report this window (the research window)",
)
ap.add_argument("--out", type=Path, default=Path("docs/stage4/cost/cost_comparison_2026-11-15.csv"))
a = ap.parse_args()
ALL = ("verified", "extracted_unverified", "assumed_backfill")
old, new = (ScheduleBook(load_schedules(d), allowed_statuses=ALL) for d in (a.old, a.new))
window = date.fromisoformat(a.start)
rows = []
with psycopg.connect(a.db) as conn:
    for run_id, cash, tr, strategy, factor in conn.execute(
        "SELECT run_id, (config->>'initial_cash')::numeric, (metrics->>'total_return')::numeric, strategy_id, COALESCE((cost_model->>'stress_factor')::numeric, 1) FROM backtest_run WHERE cost_model->>'kind'='schedule' ORDER BY run_id"
    ).fetchall():
        fills = conn.execute(
            "SELECT day, instrument_id, side, qty, price, cost FROM backtest_trade WHERE run_id=%s ORDER BY seq",
            (run_id,),
        ).fetchall()
        tot = defaultdict(Decimal)
        mismatch = 0
        dp_old: set[tuple[int, date]] = set()
        dp_new: set[tuple[int, date]] = set()
        for day, iid, side, qty, price, stored in fills:
            o = compute_charges(
                old.for_date(day), side, qty, price, dp_already_charged=(iid, day) in dp_old
            )
            n = compute_charges(
                new.for_date(day), side, qty, price, dp_already_charged=(iid, day) in dp_new
            )
            if side == "SELL":
                if o.amount("DP_CHARGE") > 0:
                    dp_old.add((iid, day))
                if n.amount("DP_CHARGE") > 0:
                    dp_new.add((iid, day))
            o_total, n_total = (
                o.total * factor,
                n.total * factor,
            )  # a cost-stress run multiplied every charge by its recorded factor
            mismatch += o_total != stored
            for scope in ("all", "window") if day >= window else ("all",):
                tot[f"old_{scope}"] += o_total
                tot[f"new_{scope}"] += n_total
                tot[f"stored_{scope}"] += stored
                tot[f"n_{scope}"] += 1
            if n.unevidenced and day >= window:
                tot["assumed_component_fills_window"] += 1
        d_all = tot["new_all"] - tot["old_all"]
        rows.append({
            "run_id": run_id, "strategy": strategy, "initial_cash": cash, "fills": len(fills), "fills_in_window": int(tot["n_window"]),
            "stored_cost": tot["stored_all"], "replayed_old_cost": tot["old_all"], "old_replay_mismatched_fills": mismatch,
            "new_cost": tot["new_all"], "cost_change": d_all, "cost_change_pct": (d_all / tot["old_all"] * 100) if tot["old_all"] else 0,
            "window_old_cost": tot["old_window"], "window_new_cost": tot["new_window"], "window_cost_change": tot["new_window"] - tot["old_window"],
            "stored_total_return": tr, "est_total_return_after_change": tr - d_all / cash,  # no compounding: the cost change taken off the final equity
            "fills_in_window_with_assumed_components": int(tot["assumed_component_fills_window"]),
        })  # fmt: skip
a.out.parent.mkdir(parents=True, exist_ok=True)
with a.out.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    for r in rows:
        w.writerow({k: (f"{v:.6f}" if isinstance(v, Decimal) else v) for k, v in r.items()})
print(
    f"{len(rows)} runs, {sum(r['fills'] for r in rows)} fills; old replay mismatched fills: {sum(r['old_replay_mismatched_fills'] for r in rows)}"
)
print(
    f"total cost old {sum(r['replayed_old_cost'] for r in rows):,.0f} -> new {sum(r['new_cost'] for r in rows):,.0f}; in the window {sum(r['window_old_cost'] for r in rows):,.0f} -> {sum(r['window_new_cost'] for r in rows):,.0f}"
)
