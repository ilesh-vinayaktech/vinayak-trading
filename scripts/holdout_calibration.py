# ruff: noqa: E501
"""Holdout policy v3 section 2.2: run or report the bootstrap calibration (and the power / pass-probability runs). A batch job, not a test; stop and resume freely.
usage: holdout_calibration.py run    --out DIR [--datasets 310000] [--workers 12] [--series 0..6 or 7] [--sharpe 0.0]
       holdout_calibration.py report --out DIR [--datasets 310000]
The 128-bit root seed is generated once and stored in DIR/root.txt; a resume reads it."""

import argparse
import json
import sys
from pathlib import Path

from algo.backtest.validation import mc_bootstrap
from algo.backtest.validation import mc_calibration as cal

ap = argparse.ArgumentParser()
ap.add_argument("cmd", choices=("run", "report", "power"))
ap.add_argument("--out", required=True, type=Path)
ap.add_argument("--datasets", type=int, default=310_000)
ap.add_argument("--draws", type=int, default=cal.DRAWS, help="bootstrap draws per dataset (a multiple of 10,000)")
ap.add_argument("--workers", type=int, default=12)
ap.add_argument(
    "--series",
    default="0,1,2,3,4,5,6",
    help="series numbers; 7 is the drift diagnostic (run it at --sharpe 0, -0.5 and -1.0)",
)
ap.add_argument("--sharpe", type=float, default=0.0)
ap.add_argument(
    "--power-datasets",
    type=int,
    default=2_000,
    help="datasets per series and Sharpe for the power runs",
)
a = ap.parse_args()
a.out.mkdir(parents=True, exist_ok=True)
rootfile = a.out / "root.txt"
if not rootfile.exists():
    rootfile.write_text(f"{mc_bootstrap.new_seed():032x}")
root = int(rootfile.read_text(), 16)
if a.cmd == "report":
    print(json.dumps(cal.report(a.out, a.datasets), indent=1, default=str))
    sys.exit(0)
series = [int(s) for s in a.series.split(",")]
if a.cmd == "power":
    for sr in (1.0, 1.4, 2.0):
        cal.run(
            root,
            a.out,
            list(range(7)),
            -(-a.power_datasets // cal.CHUNK),
            sr,
            draws=a.draws,
            workers=a.workers,
            progress=lambda i, n, sr=sr: print(f"power SR {sr}: {i}/{n}", flush=True),
        )
    sys.exit(0)
cal.run(
    root,
    a.out,
    series,
    -(-a.datasets // cal.CHUNK),
    a.sharpe,
    draws=a.draws,
    workers=a.workers,
    progress=lambda i, n: print(f"{i}/{n} chunks", flush=True),
)
