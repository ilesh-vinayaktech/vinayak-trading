# ruff: noqa: E501
"""The kill switch. PAUSE: no new orders. CANCEL: also fails approved paper orders that have not filled. FLATTEN: also asks for the
positions to be closed (needs --emergency-override; for paper it is recorded and blocks new orders, closing is still your act).
Every change is stored with who and why; resume is always explicit.
  kill_switch.py show
  kill_switch.py pause|cancel|resume [--strategy ID] --by WHO --reason TEXT
  kill_switch.py flatten [--strategy ID] --by WHO --reason TEXT --emergency-override
Without --strategy the change is global."""

import argparse
import os
import sys
from datetime import UTC, datetime

import psycopg

from algo.data.store.migrate import migrate
from algo.risk import store
from algo.risk.killswitch import KillSwitchError

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
sub = ap.add_subparsers(dest="cmd", required=True)
sub.add_parser("show")
for name in ("pause", "cancel", "resume", "flatten"):
    p = sub.add_parser(name)
    p.add_argument("--strategy")
    p.add_argument("--by", required=True)
    p.add_argument("--reason", required=True)
    if name == "flatten":
        p.add_argument("--emergency-override", action="store_true")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
with psycopg.connect(a.db, autocommit=True) as conn:
    migrate(conn)
    if a.cmd != "show":
        try:
            store.change(
                conn,
                a.cmd,
                a.strategy,
                by=a.by,
                reason=a.reason,
                now=datetime.now(UTC),
                emergency_override=getattr(a, "emergency_override", False),
            )
        except KillSwitchError as e:
            sys.exit(f"refused: {e}")
    sw = store.load(conn)
    scopes = sorted({e.scope for e in sw.events}, key=lambda s: (s is not None, s or ""))
    print(
        "kill switch:",
        ", ".join(
            f"{s or 'GLOBAL'}={sw.mode(s or '').value if s is None else sw.mode(s).value}"
            for s in scopes
        )
        or "nothing ever set (RUNNING)",
    )
    for e in sw.events[-5:]:
        print(
            f"  {e.ts:%Y-%m-%d %H:%M} {e.scope or 'GLOBAL'} -> {e.mode.value} by {e.by}: {e.reason}"
        )
