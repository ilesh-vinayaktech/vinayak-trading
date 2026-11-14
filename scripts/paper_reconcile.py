# ruff: noqa: E501
"""The paper reconciler (spec section 11: an independent watchdog, every minute in market hours and once after the close). Closes the positions of any
account whose kill switch is FLATTEN, then compares the OMS log with the paper orders and the orders' fills with what the paper book recorded.
A mismatch pauses the strategy and the job exits 1 so the runner alerts; a closing order that could not be sent also exits 1 (it is tried again next minute).
usage: paper_reconcile.py [--db URL]"""

import argparse
import os
import sys
from datetime import UTC, datetime

import psycopg

from algo.paper import oms as paper_oms

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
now = datetime.now(UTC)
with psycopg.connect(a.db, autocommit=True) as conn:
    closed = paper_oms.flatten(conn, now)
    found = paper_oms.reconcile(conn, now)
print(
    f"flatten: {len(closed.sent)} closing order(s) sent, {len(closed.refused)} refused; reconcile: {len(found)} mismatch(es)"
)
for who, iid, why in closed.refused:
    print(f"  could not close {iid} for {who}: {why}")
for m in found:
    print(f"  {m.kind} {m.client_order_id} {m.detail}")
sys.exit(1 if found or closed.refused else 0)
