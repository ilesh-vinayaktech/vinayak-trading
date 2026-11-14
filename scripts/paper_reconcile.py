# ruff: noqa: E501
"""Compare the OMS order log with the paper orders (the paper broker's book). Exit 1 when they disagree: an order the OMS has but the
broker does not, a different state or filled quantity, or a broker order the OMS never sent. Read-only.
usage: paper_reconcile.py [--db URL]"""

import argparse
import os
import sys
from datetime import UTC, datetime

import psycopg

from algo.paper import oms

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
with psycopg.connect(a.db, options="-c default_transaction_read_only=on") as conn:
    found = oms.reconcile(conn, datetime.now(UTC))
print(f"{len(found)} mismatch(es)")
for m in found:
    print(f"  {m.kind} {m.client_order_id}: {m.detail}")
sys.exit(1 if found else 0)
