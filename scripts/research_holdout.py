# ruff: noqa: E501
"""The holdout by hand (docs/holdout-policy-v3.md): the owner's commands, in the order they are used. Nothing here reads a holdout day except `evaluate`.
usage: research_holdout.py migrate                       apply database migrations
       research_holdout.py status                        slots, batches, the cutoff and what its plan would do
       research_holdout.py cutoff                        fire the Batch 1 cutoff (the worker does this by itself when the round ends)
       research_holdout.py provenance ID STATUS REASON   ID like ALPHA_VOL_20D_H5@1, STATUS ELIGIBLE | INELIGIBLE | PROVISIONAL
       research_holdout.py sign-audit --by NAME FILE     sign the procedure-provenance audit (FILE is its text, e.g. docs/holdout-audit-step0.md)
       research_holdout.py locks [--write]               strategy_locked_at and forward start per candidate (prints; --write records them)
       research_holdout.py freeze --cutoff N             freeze the batch of that cutoff (needs the audit; reserves slots, commits seeds)
       research_holdout.py evaluate --batch N --yes      the ONE evaluation of that batch: spends its slots, cannot be repeated
       research_holdout.py verdicts                      the owner's read of the verdicts"""

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from algo.data.store.migrate import migrate
from algo.promotion import verdicts
from algo.research import holdout_batch as hb
from algo.research import holdout_cutoff as co
from algo.research import holdout_evaluator as ev
from algo.research import holdout_locks as hl
from algo.research import slot

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
sub = ap.add_subparsers(dest="cmd", required=True)
for name in ("migrate", "status", "cutoff", "verdicts"):
    sub.add_parser(name)
p = sub.add_parser("provenance")
p.add_argument("candidate")
p.add_argument("status", choices=("ELIGIBLE", "INELIGIBLE", "PROVISIONAL"))
p.add_argument("reason")
s = sub.add_parser("sign-audit")
s.add_argument("--by", required=True)
s.add_argument("file", type=Path)
lk = sub.add_parser("locks")
lk.add_argument("--write", action="store_true")
f = sub.add_parser("freeze")
f.add_argument("--cutoff", type=int, required=True)
e = sub.add_parser("evaluate")
e.add_argument("--batch", type=int, required=True)
e.add_argument("--yes", action="store_true", help="confirm that the batch's slots will be spent")
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
now = datetime.now(UTC)
with psycopg.connect(a.db, autocommit=True) as conn:
    try:
        if a.cmd == "migrate":
            migrate(conn)
            print("migrations applied")
        elif a.cmd == "status":
            consumed, reserved, left = hb.slots(conn)
            print(f"slots: {consumed} consumed, {reserved} reserved, {left} left of {hb.BUDGET}")
            for row in conn.execute(
                "SELECT batch_id, state, frozen_at, first_read_at FROM holdout_batch ORDER BY 1"
            ):
                print("batch", *row)
            cut = conn.execute(
                "SELECT cutoff_id, kind, fired_at FROM holdout_cutoff ORDER BY 1 DESC LIMIT 1"
            ).fetchone()
            print("cutoff", cut or "not fired yet")
            if cut:
                pl = co.plan(conn, cut[0])
                print(
                    "  members:",
                    list(pl.members),
                    "| carry over:",
                    list(pl.carry_over),
                    "| excluded:",
                    pl.excluded,
                    "\n  problems:",
                    list(pl.problems),
                )
        elif a.cmd == "cutoff":
            print(
                "cutoff",
                co.fire_batch1(conn, now)
                or "not fired: already fired, or the round is not complete",
            )
        elif a.cmd == "provenance":
            co.record_provenance(conn, a.candidate, a.status, a.reason, now)
            print("recorded", a.candidate, a.status)
        elif a.cmd == "sign-audit":
            print("audit signed:", co.sign_audit(conn, a.by, a.file.read_text(), now))
        elif a.cmd == "locks":
            ok, refused = hl.compute_all(conn)
            for r in ok:
                print(
                    r["candidate_id"],
                    r["strategy_locked_at"].isoformat(timespec="minutes"),
                    "-> forward start",
                    r["forward_evaluation_start"],
                )
                if a.write:
                    hl.record(conn, r, now)
            for k, why in refused.items():
                print("REFUSED", k, why)
        elif a.cmd == "freeze":
            print(
                "frozen batch",
                co.freeze_batch(conn, a.cutoff, "owner", now)
                or "none: " + "; ".join(co.plan(conn, a.cutoff).problems),
            )
        elif a.cmd == "evaluate":
            if not a.yes:
                raise SystemExit(
                    "this spends the batch's slots and cannot be repeated: pass --yes to go ahead"
                )
            with slot.hold(conn, "holdout evaluation", nice=10):
                ev.run_batch(conn, a.batch, now)
            print("evaluated: the batch's slots are consumed; read the verdicts with `verdicts`")
        else:
            for row in verdicts.read_verdicts(conn):
                print(*row)
    except (hb.BatchError, hl.LockError) as err:
        sys.exit(f"refused: {err}")
