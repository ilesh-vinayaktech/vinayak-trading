# ruff: noqa: E501
"""One-shot run of the frozen HOLD_SIGNAL_V1 rule on the 2025-2026 holdout window, directed by the owner (an ad hoc read outside holdout policy v3's batch route: NON-CONFIRMATORY, see the spec's `holdout_run`).

Before any holdout bar is read this script checks that nothing moved since the freeze: the spec's own hash, the sha256 of every script it lists, the DB cost schedules, and that the lock file still says what the spec says.
It then writes the consumed-marker (exclusive create: a second run is impossible, also after a failure) and only then starts the study with the frozen arguments.
usage: run_holdout_hold_signal_v1.py --confirm-single-use"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
W = ROOT / "data/research/winner_v2"
SPEC, MARKER, LOG, TRADES = (
    W / "frozen_HOLD_SIGNAL_V1.json",
    W / "holdout_HOLD_SIGNAL_V1.consumed.json",
    W / "holdout_HOLD_SIGNAL_V1.log",
    W / "holdout_HOLD_SIGNAL_V1_trades.csv",
)

ap = argparse.ArgumentParser()
ap.add_argument(
    "--confirm-single-use",
    action="store_true",
    help="I understand the 2025-2026 window is read exactly once",
)
a = ap.parse_args()
if not a.confirm_single_use:
    sys.exit("refusing: pass --confirm-single-use (the holdout window is read exactly once)")
if MARKER.exists():
    sys.exit(f"refusing: the holdout was already read ({MARKER.name}); it is never run twice")

spec = json.loads(SPEC.read_text())
recorded = spec.pop("spec_sha256_of_the_rest")
if hashlib.sha256(json.dumps(spec, indent=2, sort_keys=True).encode()).hexdigest() != recorded:
    sys.exit("refusing: the frozen spec was altered after it was hashed")
for f, h in spec["code_sha256"].items():
    if hashlib.sha256((ROOT / f).read_bytes()).hexdigest() != h:
        sys.exit(f"refusing: {f} changed since the freeze")
cfg = json.loads((ROOT / "config/research_holdout.json").read_text())
args = spec["holdout_run"]["command_args"]
if (args["end"], args["universe_end"]) != (cfg["holdout_end"], cfg["development_end"]):
    sys.exit("refusing: the lock file's dates differ from the frozen run")
db = os.environ.get("ALGO_DB_URL") or sys.exit("error: ALGO_DB_URL not set")
with psycopg.connect(db) as conn:
    now = [
        {
            "schedule_id": r[0],
            "version": r[1],
            "valid_from": str(r[2]),
            "valid_until": str(r[3]) if r[3] else None,
            "status": r[4],
            "doc_hash": r[5],
        }
        for r in conn.execute(
            "SELECT schedule_id, version, valid_from, valid_until, status, doc_hash FROM cost_schedule WHERE broker='zerodha' AND product='DELIVERY' ORDER BY valid_from"
        )
    ]
if now != spec["costs"]["schedules"]:
    sys.exit("refusing: the cost schedules in the database differ from the frozen ones")

cmd = [
    sys.executable,
    "-u",
    str(ROOT / "scripts/study_hold_signal_folds.py"),
    "--start",
    args["start"],
    "--end",
    args["end"],
    "--universe-end",
    args["universe_end"],
    "--folds",
    args["folds"],
    "--max-positions",
    str(args["max_positions"]),
    "--dump",
    str(TRADES),
]
with open(
    MARKER, "x"
) as fh:  # exclusive create: the read is consumed from this moment, whatever happens next
    json.dump(
        {
            "started_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "spec_sha256": recorded,
            "authorisation": spec["holdout_run"]["authorisation"],
            "command": cmd,
        },
        fh,
        indent=2,
    )
print(
    f"all freeze checks passed; marker written; reading the holdout window {cfg['holdout_start']}..{cfg['holdout_end']} once",
    flush=True,
)
with open(LOG, "w") as lg:
    rc = subprocess.run(cmd, stdout=lg, stderr=subprocess.STDOUT, cwd=ROOT, check=False).returncode
m = json.loads(MARKER.read_text())
m.update(
    {
        "finished_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "returncode": rc,
        "log": LOG.name,
    }
)
MARKER.write_text(json.dumps(m, indent=2))
print(f"finished with return code {rc}; log {LOG}")
