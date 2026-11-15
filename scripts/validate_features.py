# ruff: noqa: E501
"""Validate features against one data freeze and, for the ones that pass, set them USABLE (docs/vti-phase1-spec.md item F). Each report is stored
(feature_validation) and a status change names it. Failed features stay as they were. Exit 1 when any feature failed.
usage: validate_features.py [--db URL] [--freeze UUID (default: the newest)] [--from YYYY-MM-01] [--min-coverage 0.90] [--by NAME] [FEATURE ...] [--dry-run]"""

import argparse
import os
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import psycopg

from algo.core.clock import SystemClock
from algo.features import job, registry, store, validation
from algo.jobs import progress
from algo.research import slot

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--freeze")
ap.add_argument("--from", dest="first", default="2020-10-01")
ap.add_argument("--min-coverage", default=str(validation.MIN_COVERAGE))
ap.add_argument("--by", default="validate_features")
ap.add_argument("--dry-run", action="store_true", help="validate and print, store nothing")
ap.add_argument("names", nargs="*", help="features to validate (default: all registered)")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")

failed = 0
with psycopg.connect(a.db, autocommit=True) as conn, slot.hold(conn, "feature validation", nice=10):
    fid = (
        a.freeze
        or (
            conn.execute(
                "SELECT freeze_id FROM data_freeze ORDER BY taken_at DESC LIMIT 1"
            ).fetchone()
            or [None]
        )[0]
    )
    if fid is None:
        sys.exit("error: no data freeze")
    store.register_all(conn, datetime.now(UTC))
    names = a.names or list(registry.DEFINITIONS)
    sha = job.dataset_sha256(
        conn,
        UUID(str(fid)),
        [
            i[0]
            for i in conn.execute(
                "SELECT instrument_id FROM data_freeze_item WHERE freeze_id=%s ORDER BY 1",
                (str(fid),),
            )
        ],
    )
    with (
        psycopg.connect(
            a.db, autocommit=True
        ) as pconn,  # its own connection: each progress update shows at once
        progress.Progress(
            pconn,
            SystemClock(),
            "feature_validation",
            "Feature validation" + (" (dry run)" if a.dry_run else ""),
            len(names),
        ) as prog,
    ):
        reads = validation.read_bars(
            conn, UUID(str(fid)), date.fromisoformat(a.first), report=prog.step
        )
        for k, name in enumerate(names):
            r = validation.validate(
                conn,
                name,
                registry.VERSION,
                UUID(str(fid)),
                date.fromisoformat(a.first),
                min_coverage=Decimal(a.min_coverage),
                reads=reads,
                report=prog.step,
            )
            rid = (
                None
                if a.dry_run
                else validation.record(
                    conn, name, registry.VERSION, sha, r, by=a.by, now=datetime.now(UTC)
                )
            )
            line = (
                f"{name}: {'PASS' if r['passed'] else 'FAIL'} coverage {r['coverage']['share']} lookahead {r['lookahead']['violations']}"
                + (f" report {rid}" if rid else "")
                + "".join(f"\n    {x}" for x in r["reasons"])
            )
            print(line, flush=True)
            prog.step(f"checked {name}", line.splitlines()[0], done=k + 1)
            failed += not r["passed"]
sys.exit(1 if failed else 0)
