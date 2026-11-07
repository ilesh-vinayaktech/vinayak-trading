"""Load every config/transcriptions/*.json (OCR/hand transcriptions of scanned releases) as
PROVISIONAL rows, after checking each source hash against the stored original. Idempotent.
usage: apply_transcriptions.py --lake data/lake --db postgresql://..."""

import argparse
import json
import os
from datetime import date
from pathlib import Path

import psycopg

from algo.data.lake import LocalLake
from algo.data.store.migrate import migrate
from algo.data.transcriptions import store_transcription

ap = argparse.ArgumentParser()
ap.add_argument("--lake", required=True, type=Path)
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--dir", type=Path, default=Path("config/transcriptions"))
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
lake = LocalLake(a.lake)
with psycopg.connect(a.db, autocommit=True) as conn:
    migrate(conn)
    for f in sorted(a.dir.glob("*.json")):
        doc = json.loads(f.read_text())
        m = lake.versions("niftyindices", doc["doc_id"], date.fromisoformat(doc["announced"]))[-1]
        n = store_transcription(conn, doc, actual_sha256=m.checksum)
        print(f"{doc['doc_id']}: {n} rows stored ({len(doc['rows'])} in the file)")
