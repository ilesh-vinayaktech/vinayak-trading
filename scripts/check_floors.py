"""T0.3: per-package branch-coverage floors. Run after `coverage` data exists."""

import json
import subprocess
import sys

FLOORS = {
    "src/algo/risk": 100,
    "src/algo/execution": 100,
    "src/algo/ledger": 100,
    "src/algo/data/adjust": 100,
    "src/algo/backtest/costs": 100,
    "src/algo/platform_state": 100,
    "src/algo/core/money.py": 100,
}

out = subprocess.run(["coverage", "json", "-q", "-o", "-"], check=True, capture_output=True)
files = json.loads(out.stdout)["files"]
bad = []
for prefix, floor in FLOORS.items():
    sel = [f["summary"] for p, f in files.items() if p.startswith(prefix)]
    if not sel:
        continue  # package not built yet
    stmts = sum(s["num_statements"] for s in sel)
    br = sum(s["num_branches"] for s in sel)
    hit = sum(s["covered_lines"] for s in sel) + sum(s["covered_branches"] for s in sel)
    pct = 100 * hit / max(stmts + br, 1)
    if pct < floor:
        bad.append(f"{prefix}: {pct:.1f}% < {floor}%")
sys.exit("\n".join(bad) if bad else 0)
