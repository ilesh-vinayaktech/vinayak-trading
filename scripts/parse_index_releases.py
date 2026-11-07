"""Parse every stored NSE Indices press release (--since onward) into PROVISIONAL evidence rows and
print what a person must still look at. Re-runnable (idempotent per document + parser version).
usage: parse_index_releases.py --lake data/lake --db postgresql://... [--since 2017-01-01]"""

import argparse
import os
from datetime import UTC, date, datetime
from pathlib import Path

import psycopg

from algo.data.index_releases import store_release, unresolved
from algo.data.lake import LocalLake
from algo.data.providers.nse_index_releases import extract_pages, parse_release
from algo.data.store.migrate import migrate

ap = argparse.ArgumentParser()
ap.add_argument("--lake", required=True, type=Path)
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--since", default="2017-01-01")
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
lake, since, now = LocalLake(a.lake), date.fromisoformat(a.since), datetime.now(UTC)
kinds: dict[str, int] = {}
with psycopg.connect(a.db, autocommit=True) as conn:
    migrate(conn)
    for part_dir in sorted((a.lake / "raw" / "niftyindices").glob("pr_*/dt=*")):
        d = date.fromisoformat(part_dir.name[3:])
        if d < since:
            continue
        doc = part_dir.parent.name
        m = lake.versions("niftyindices", doc, d)[-1]
        release = parse_release(extract_pages(lake.get(m)), d)
        store_release(conn, doc, release, source_url=m.url, source_hash=m.checksum, now=now)
        kinds[release.kind] = kinds.get(release.kind, 0) + 1
    print("documents by kind:", kinds)
    u = unresolved(conn)
    print(f"\nMANUAL REVIEW documents ({len(u['manual_documents'])}):")
    for doc, ann in u["manual_documents"]:
        print(f"  {ann}  {doc}")
    print(f"\nUnmapped / placeholder Nifty-200-component rows ({len(u['unmapped_rows'])}):")
    for status, sym, doc, eff in u["unmapped_rows"]:
        print(f"  {eff}  {status:20} {sym:14} {doc}")
