"""Record documented supersessions between press releases. Every override cites the superseding
release and a LITERAL quote, which is checked against the stored document before it is written.
usage: record_overrides.py --lake data/lake --db postgresql://..."""

import argparse
import os
from datetime import UTC, date, datetime
from pathlib import Path

import psycopg

from algo.data.lake import LocalLake
from algo.data.providers.nse_index_releases import extract_pages
from algo.data.store.migrate import migrate
from algo.data.universe_build import add_override

# 2020-05-13: the March 2020 rebalancing (deferred on 2020-03-23) is void, except Nifty 50 / Nifty
# Bank, which were already rebalanced on 2020-03-19 (their rows are duplicated in the 2020-03-16
# release, which stands).
QUOTE = "shall stand null and void"
AUTHORITY = "pr_ind_prs13052020"
VOIDED_DOCS = [  # (superseded release, the date its rows were announced for)
    ("pr_ind_prs18022020", date(2020, 3, 27)),
    ("pr_ind_prs12032020", date(2020, 3, 27)),
    ("pr_ind_prs19032020", date(2020, 3, 27)),
]

ap = argparse.ArgumentParser()
ap.add_argument("--lake", required=True, type=Path)
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
lake = LocalLake(a.lake)
m = next(m for p in (a.lake / "raw/niftyindices" / AUTHORITY).glob("dt=*") for m in lake.versions(
    "niftyindices", AUTHORITY, date.fromisoformat(p.name[3:])))  # fmt: skip
text = " ".join(" ".join(extract_pages(lake.get(m))).split())
if QUOTE not in text:
    raise SystemExit(f"quote not found in {AUTHORITY}: refusing to record the override")
with psycopg.connect(a.db, autocommit=True) as conn:
    migrate(conn)
    for doc, eff in VOIDED_DOCS:
        add_override(conn, doc_id=doc, effective_from=eff, authority_doc=AUTHORITY,
                     authority_quote=QUOTE, now=datetime.now(UTC))  # fmt: skip
        print(f"VOID {doc} rows effective {eff}  (authority {AUTHORITY}: '{QUOTE}')")
