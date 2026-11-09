# ruff: noqa: E501  (a report script)
"""Split one instrument at an ISIN change (default: NESTLEIND, instrument 1589, 2024-01-05).

DRY RUN BY DEFAULT: the schema migrations and the whole split run inside one transaction that is rolled
back, so the database ends exactly as it began while every step and every post-check really executed on
the real data. `--apply` commits; it needs the explicit flag and is NOT to be run before the dry-run
report has been reviewed.
usage: migrate_isin_change.py --db postgresql://... [--instrument 1589] [--old-isin INE239A01016]
       [--change 2024-01-05] [--first-observed 2010-01-08] [--decision-id 15] [--apply]
       [--out docs/stage4/apply_proposals/nestleind_migration_dry_run.json]"""

import argparse
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path

import psycopg

from algo.data.identity_migration import migrate_isin_change
from algo.data.store.migrate import migrate

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--instrument", type=int, default=1589)
ap.add_argument("--old-isin", default="INE239A01016")
ap.add_argument("--change", default="2024-01-05")
ap.add_argument("--first-observed", default="2010-01-08")
ap.add_argument("--decision-id", type=int, default=15)
ap.add_argument("--apply", action="store_true")
ap.add_argument(
    "--out", type=Path, default=Path("docs/stage4/apply_proposals/nestleind_migration_dry_run.json")
)
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
kw = dict(
    new_id=a.instrument, old_isin=a.old_isin, change=date.fromisoformat(a.change),
    first_observed=date.fromisoformat(a.first_observed), decision_id=a.decision_id,
    evidence=["NSE circular NSE/CML/60084 (2024-01-02): ISIN INE239A01024 w.e.f. 2024-01-05", "review decision #15"],
    now=datetime.now(UTC),
)  # fmt: skip
with psycopg.connect(a.db, autocommit=True) as conn:
    if a.apply:
        migrate(conn)
        audit = migrate_isin_change(conn, dry_run=False, **kw)
    else:
        with conn.transaction(force_rollback=True):  # the schema migrations too are rolled back
            migrate(conn)
            audit = migrate_isin_change(conn, dry_run=False, **kw)
        audit["applied"] = False
        audit["mode"] = "DRY RUN: everything executed and was rolled back"
a.out.parent.mkdir(parents=True, exist_ok=True)
a.out.write_text(json.dumps(audit, indent=1, default=str) + "\n")
print(json.dumps({k: v for k, v in audit.items() if k != "checks"}, indent=1, default=str))
failed = [k for k, v in audit.get("checks", {}).items() if not v]
print("checks:", len(audit.get("checks", {})), "failed:", failed)
raise SystemExit(1 if failed else 0)
