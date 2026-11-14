# ruff: noqa: E501
"""Close every open corporate-action review item whose ex-date is on or before --through: with
ALGO_PRICE_SOURCE=kite the price series is Kite's, already adjusted by the vendor through that day
(bar_1d.adjusted_through), so there is nothing left for a person to decide. Each item gets an
append-only resolution (ignored_with_reason, method ignore) that a later resolution supersedes.
NOT valid for the bhavcopy (raw NSE) feed: flipping the price source needs a stitched series
(Kite up to the cutoff, NSE after) or these items must be reopened.
usage: close_kite_covered.py --through YYYY-MM-DD [--note-evidence TEXT] [--apply]   (dry run unless --apply)"""

import argparse
import os
from collections import Counter
from datetime import UTC, date, datetime

import psycopg

from algo.data.review import ResolveError, resolve, review_queue

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--through", required=True, type=date.fromisoformat)
ap.add_argument("--evidence", default="", help="how the Kite/NSE match was checked")
ap.add_argument("--apply", action="store_true")
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
BY = "claude:kite-covered bulk close"
done: Counter[str] = Counter()
failed = 0
with psycopg.connect(a.db, autocommit=True) as conn:
    for it in review_queue(conn):
        if it.ex_date > a.through:
            continue
        done[it.kind] += 1
        if not a.apply:
            continue
        try:
            resolve(conn, symbol=it.symbol, ex_date=it.ex_date, kind=it.kind, method="ignore",
                    status="ignored_with_reason", by=BY, now=datetime.now(UTC),
                    note=f"Covered by Kite's adjusted daily series through {a.through} (price source kite). "
                    f"Reopen if the raw NSE feed is used for this period. {a.evidence}".strip())  # fmt: skip
        except ResolveError as e:
            failed += 1
            print("FAILED", it.symbol, it.ex_date, it.kind, e)
print(
    f"{'closed' if a.apply else 'would close'} {sum(done.values())} items {dict(done)}; {failed} failed"
)
