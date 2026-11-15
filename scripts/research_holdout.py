# ruff: noqa: E501
"""The one global holdout, by hand: register the (only) batch, freeze its manifest from named studies, evaluate it ONCE, read the verdicts.
`evaluate` spends the holdout: it cannot be repeated, and it needs --yes. Nothing here reads a holdout day except `evaluate`.
usage: research_holdout.py status
       research_holdout.py register --by NAME
       research_holdout.py freeze --batch N --studies 12 13 ...
       research_holdout.py evaluate --batch N --yes
       research_holdout.py verdicts"""

import argparse
import os
import sys
from datetime import UTC, datetime

import psycopg

from algo.research import holdout_batch as hb
from algo.research import holdout_evaluator as ev

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
sub = ap.add_subparsers(dest="cmd", required=True)
sub.add_parser("status")
sub.add_parser("verdicts")
r = sub.add_parser("register")
r.add_argument("--by", required=True)
f = sub.add_parser("freeze")
f.add_argument("--batch", type=int, required=True)
f.add_argument("--studies", type=int, nargs="+", required=True)
e = sub.add_parser("evaluate")
e.add_argument("--batch", type=int, required=True)
e.add_argument("--yes", action="store_true", help="confirm that the holdout will be spent")
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
now = datetime.now(UTC)
with psycopg.connect(a.db, autocommit=True) as conn:
    try:
        if a.cmd == "status":
            rows = conn.execute(
                "SELECT batch_id, state, manifest_sha256, frozen_at, finished_at FROM holdout_batch"
            ).fetchall()
            print(rows or "no batch registered")
        elif a.cmd == "register":
            print("registered batch", hb.register(conn, by=a.by, now=now))
        elif a.cmd == "freeze":
            m = ev.build_manifest(conn, a.batch, a.studies)
            print(
                "frozen, manifest sha256",
                hb.freeze(conn, a.batch, m, now),
                "candidates",
                [c.candidate_id for c in m.candidates],
                "family trials",
                dict(m.family_trials),
            )
        elif a.cmd == "evaluate":
            if not a.yes:
                raise SystemExit(
                    "this spends the one holdout and cannot be repeated: pass --yes to go ahead"
                )
            ev.run_batch(conn, a.batch, now)
            print("evaluated: the holdout is consumed; read the verdicts with `verdicts`")
        else:
            for row in hb.read_verdicts(conn):
                print(*row)
    except hb.BatchError as err:
        sys.exit(f"refused: {err}")
