"""Load every config/placeholder_replacements/*.json (the listing took over its DUMMY placeholder's
index membership) after checking each source hash against the stored original and the releases'
own rows. Idempotent. Run after parse_index_releases.py.
usage: apply_placeholder_replacements.py --lake data/lake --db postgresql://..."""

import argparse
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path

import psycopg

from algo.data.lake import LocalLake
from algo.data.placeholder_replacements import store_replacements
from algo.data.store.migrate import migrate

ap = argparse.ArgumentParser()
ap.add_argument("--lake", required=True, type=Path)
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--dir", type=Path, default=Path("config/placeholder_replacements"))
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
lake = LocalLake(a.lake)
with psycopg.connect(a.db, autocommit=True) as conn:
    migrate(conn)
    for f in sorted(a.dir.glob("*.json")):
        doc = json.loads(f.read_text())
        m = lake.versions(
            "niftyindices", doc["evidence_doc"], date.fromisoformat(doc["announced"])
        )[-1]
        n = store_replacements(conn, doc, actual_sha256=m.checksum, now=datetime.now(UTC))
        total = len(doc["replacements"])
        print(f"{doc['evidence_doc']}: {n} replacements stored ({total} in the file)")
