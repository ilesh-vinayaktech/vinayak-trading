# ruff: noqa: E501  (a report script)
"""Record the reviewed ISIN-change conversion instructions in config/security_conversions/*.json.

DRY RUN BY DEFAULT: the schema migration and the insert run inside a transaction that is rolled back, and the
instruction that WOULD be recorded is printed. `--apply` commits. A VERIFIED instruction is what makes the
ledger convert a held position; until it is recorded, such a position is flagged as unmodelled.
usage: record_security_conversion.py --db postgresql://... [--dir config/security_conversions] [--apply]"""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from algo.data.conversions import store_conversion
from algo.data.store.migrate import migrate

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--dir", type=Path, default=Path("config/security_conversions"))
ap.add_argument("--apply", action="store_true")
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
docs = [(f.name, json.loads(f.read_text())) for f in sorted(a.dir.glob("*.json"))]


def run(conn: psycopg.Connection) -> None:
    migrate(conn)
    for name, doc in docs:
        n = store_conversion(conn, doc, datetime.now(UTC))
        print(
            f"{name}: {'recorded' if n else 'already recorded'} ({doc['source_isin']} -> {doc['target_isin']}"
            f" from {doc['effective_date']}, {doc['ratio_num']}:{doc['ratio_den']}, {doc['verification_status']})"
        )


with psycopg.connect(a.db, autocommit=True) as conn:
    if a.apply:
        run(conn)
    else:
        with conn.transaction(force_rollback=True):
            run(conn)
        print("DRY RUN: nothing was written (the migration and the insert were rolled back)")
