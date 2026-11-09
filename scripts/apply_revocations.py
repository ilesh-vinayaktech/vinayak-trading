"""Load every config/revocations/*.json (row-level revocations of announced index changes) after
checking each source hash against the stored original and that the revoked change was really
announced. Idempotent. Run after parse_index_releases.py and apply_transcriptions.py.
usage: apply_revocations.py --lake data/lake --db postgresql://..."""

import argparse
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path

import psycopg

from algo.data.lake import LocalLake
from algo.data.revocations import store_revocations
from algo.data.store.migrate import migrate

ap = argparse.ArgumentParser()
ap.add_argument("--lake", required=True, type=Path)
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--dir", type=Path, default=Path("config/revocations"))
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
lake = LocalLake(a.lake)
with psycopg.connect(a.db, autocommit=True) as conn:
    migrate(conn)
    for f in sorted(a.dir.glob("*.json")):
        doc = json.loads(f.read_text())
        m = lake.versions(
            "niftyindices", doc["authority_doc"], date.fromisoformat(doc["announced"])
        )[-1]
        n = store_revocations(conn, doc, actual_sha256=m.checksum, now=datetime.now(UTC))
        total = len(doc["revocations"])
        print(f"{doc['authority_doc']}: {n} revocations stored ({total} in the file)")
