"""Plan (default) or apply (--apply) the creation of delisted instruments for former index members,
then reload the bhavcopy days that dropped them so their price history is loaded.
usage: build_delisted.py --lake data/lake --db postgresql://... [--apply]"""

import argparse
import os
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from algo.data.delisted import (
    create_instruments,
    extend_inferred_aliases,
    load_symbols,
    partitions_to_reload,
    plan,
)  # fmt: skip
from algo.data.index_releases import remap
from algo.data.lake import LocalLake
from algo.data.store.migrate import migrate

ap = argparse.ArgumentParser()
ap.add_argument("--lake", required=True, type=Path)
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--apply", action="store_true")
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")

with psycopg.connect(a.db, autocommit=True) as conn:
    migrate(conn)
    cands = plan(conn)
    for c in cands:
        print(
            f"{c.action:30} {c.symbol:12} first={c.first_evidence} last={c.last_traded} {c.reason}"
        )
    if not a.apply:
        raise SystemExit("\n(dry run: nothing written; pass --apply)")
    lake = LocalLake(a.lake)
    created = create_instruments(conn, cands)
    print(f"\ncreated {len(created)} instruments")
    now = datetime.now(UTC)
    days = partitions_to_reload(conn, set(created))
    rows = sum(load_symbols(conn, lake, d, set(created), now) for d in days)
    print(f"extended {extend_inferred_aliases(conn)} inferred aliases back to earlier evidence")
    print(f"remapped {remap(conn)} press-release rows to instruments")
    print(f"loaded {rows} bars for them from {len(days)} stored bhavcopy days")
