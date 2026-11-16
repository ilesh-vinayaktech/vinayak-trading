# ruff: noqa: E501
"""Turn the alpha registry's CANDIDATE hypotheses into registered strategy definitions (algo.factory.generate): one per feature and horizon, built from fixed priors only, never
validated or promoted here. Candidates the strategy language cannot express are listed with their reason. Safe to re-run: what exists is left alone.
usage: generate_strategies.py [--db URL] [--by NAME] [--dry-run]"""

import argparse
import os
import sys
from datetime import UTC, datetime

import psycopg

from algo.core.clock import SystemClock
from algo.factory import generate
from algo.jobs import progress

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--by", default="generate_strategies")
ap.add_argument("--dry-run", action="store_true", help="show what would be written, store nothing")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
with psycopg.connect(a.db, autocommit=True) as conn:
    if a.dry_run:
        for h in generate.candidates(conn):
            try:
                print(
                    f"would register {generate.definition_for(h).strategy_id} from hypothesis {h.hypothesis_id}"
                )
            except generate.NotExpressible as e:
                print(
                    f"refused hypothesis {h.hypothesis_id} ({h.feature} at {h.horizon} days): {e}"
                )
        sys.exit(0)
    with progress.Progress(
        conn, SystemClock(), "strategy_registration", "Register strategies", 1, uniform=False
    ) as prog:
        prog.step("registering", "writing one definition per candidate", done=0)
        r = generate.generate_from_candidates(conn, by=a.by, now=datetime.now(UTC))
        prog.finish(
            True,
            f"{len(r.created)} registered, {len(r.existing)} already there, {len(r.refused)} refused",
        )
for c in r.created:
    print(f"registered {c.strategy_id} from hypothesis {c.hypothesis_id}")
for sid in r.existing:
    print(f"already registered: {sid}")
for x in r.refused:
    print(f"refused hypothesis {x.hypothesis_id} ({x.feature} at {x.horizon} days): {x.reason}")
print(f"{len(r.created)} registered, {len(r.existing)} already there, {len(r.refused)} refused")
