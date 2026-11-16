# ruff: noqa: E501
"""Print a PBO diagnostic for each named study (a markdown report): where the overfitting probability comes from. Read-only.
usage: pbo_diagnostic.py "STUDY NAME" ["STUDY NAME" ...] [--db URL]"""

import argparse
import os
import sys

import psycopg

from algo.research import pbo_diagnostic

ap = argparse.ArgumentParser()
ap.add_argument("names", nargs="+")
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")


def pct(x: float | None) -> str:
    return "-" if x is None else f"{x:.0%}"


with psycopg.connect(a.db) as conn:
    for name in a.names:
        row = conn.execute(
            "SELECT experiment_id FROM experiment WHERE name = %s", (name,)
        ).fetchone()
        if row is None:
            sys.exit(f"error: no study called {name!r}")
        trials = conn.execute(
            "SELECT params, returns, backtest_run FROM study_trial WHERE experiment_id = %s AND status = 'DONE' ORDER BY params",
            (row[0],),
        ).fetchall()
        series = [t[1] for t in trials]
        labels = [", ".join(f"{k} {v}" for k, v in sorted(t[0].items())) for t in trials]
        days = [
            d
            for (d,) in conn.execute(
                "SELECT day FROM backtest_equity WHERE run_id = %s ORDER BY day", (trials[0][2],)
            )
        ][1:]  # a return per day after the first
        size = len(series[0]) // pbo_diagnostic.N_BLOCKS
        names_b = (
            [
                f"{days[b * size]:%Y-%m} to {days[(b + 1) * size - 1]:%Y-%m}"
                for b in range(pbo_diagnostic.N_BLOCKS)
            ]
            if len(days) >= len(series[0])
            else []
        )
        d = pbo_diagnostic.diagnose(series, labels, names_b)
        dist = d["distribution"]
        print(f"\n## {name}\n")
        print(
            f"PBO {d['pbo']:.2f} over {d['partitions']} partitions ({d['bad_partitions']} with the in-sample winner at or below the out-of-sample median). To reach the allowed 0.20, {d['flips_needed_for_threshold']} of them would have to turn good."
        )
        print(
            f"\nSensitivity to how the history is cut (blocks -> PBO): {', '.join(f'{k} -> {v:.2f}' for k, v in d['sensitivity_to_block_count'].items())}"
        )
        print(
            "\n### 1-4. Each variant: how often it wins in sample, and how it ranks out of sample (rank 1 = worst of the variants)\n"
        )
        print(
            "| variant | wins in sample | share | out-of-sample rank when it wins | PBO when it wins | in-sample Sharpe when it wins | out-of-sample Sharpe when it wins | mean out-of-sample rank overall |"
        )
        print("|---|---|---|---|---|---|---|---|")
        for c in d["by_config"]:
            m = c["mean_oos_rank_when_winner"]
            print(
                f"| {c['config']} | {c['winner_count']} | {pct(c['winner_share'])} | {'-' if m is None else f'{m:.1f}'} | {pct(c['pbo_when_winner'])} | {'-' if c['mean_is_sharpe_when_winner'] is None else f'{c["mean_is_sharpe_when_winner"]:.3f}'} | {'-' if c['mean_oos_sharpe_when_winner'] is None else f'{c["mean_oos_sharpe_when_winner"]:.3f}'} | {c['mean_oos_rank_overall']:.1f} |"
            )
        print("\n### 2. Distribution over partitions\n")
        q = dist["logit_quantiles"]
        print(
            f"- Logit of the winner's out-of-sample rank (at or below 0 counts as overfit): min {q[0]:.2f}, 25% {q[1]:.2f}, median {q[2]:.2f}, 75% {q[3]:.2f}, max {q[4]:.2f}"
        )
        print(
            f"- Out-of-sample rank of the in-sample winner (1 = worst of {len(series)}): "
            + ", ".join(f"{r}: {n}" for r, n in dist["winner_oos_rank_counts"].items())
        )
        print(
            f"- Mean per-day Sharpe of the in-sample winner: in sample {dist['winner_is_sharpe_mean']:.3f}, out of sample {dist['winner_oos_sharpe_mean']:.3f}; the average variant out of sample {dist['all_oos_sharpe_mean']:.3f}"
        )
        print("\n### 5-6. By period: is the instability in particular years?\n")
        print(
            "| period (block) | average variant annual return | PBO when this block is out of sample | PBO when it is in sample |"
        )
        print("|---|---|---|---|")
        for b in d["by_block"]:
            print(
                f"| {b['block']} | {b['avg_variant_annual_return']:.1%} | {pct(b['pbo_when_out_of_sample'])} | {pct(b['pbo_when_in_sample'])} |"
            )
