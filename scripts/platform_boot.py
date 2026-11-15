# ruff: noqa: E501
"""The daily boot of the platform (docs: TODO 1.2 and 5.3): INITIALIZING -> DATA_VALIDATION -> READY -> PAPER, recording each step. READY needs every
recovery check: the daily data is current, there is a valid Kite session, the OMS log and the paper orders agree, positions agree, the order log loads.
Exit 1 unless the platform ends in PAPER or LIVE, so the job runner alerts. A HALTED platform is not restarted by this: only --operator clears it.
The paper account's cash has no broker side to compare, so that check is recorded as passed with that reason.
usage: platform_boot.py [--db URL] [--mode PAPER|LIVE] [--operator]"""

import argparse
import os
import sys
from datetime import UTC, datetime

import psycopg

from algo.api import freshness, queries
from algo.paper import oms as paper_oms
from algo.platform_state.boot import Probe, Probes, boot
from algo.platform_state.machine import TRADING, State
from algo.portal.crypto import KeyRing
from algo.portal.kite_vault import system_feed_credentials

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--mode", choices=["PAPER", "LIVE"], default="PAPER")
ap.add_argument("--operator", action="store_true", help="an operator clears a HALTED platform")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
now = datetime.now(UTC)
with psycopg.connect(a.db, autocommit=True) as conn:

    def data_fresh() -> Probe:
        last = queries.data_health(conn)["last_date"]
        if last is None:
            return Probe(False, "there are no daily bars at all")
        r = freshness.assess(datetime.fromisoformat(last).date(), now, queries.known_holidays(conn))
        return Probe(r["status"] == "CURRENT", f"daily data is {r['status']}")

    def session() -> Probe:
        ok = system_feed_credentials(conn, KeyRing.from_env(os.environ), now=now) is not None
        return Probe(
            ok,
            "a Kite data feed is connected"
            if ok
            else "no valid Kite session (the daily login is manual)",
        )

    def orders() -> Probe:
        found = paper_oms.reconcile(
            conn, now
        )  # also pauses a strategy on a mismatch, as the reconciler job does
        return Probe(
            not found,
            f"{len(found)} mismatch(es) between the OMS log and the paper orders"
            if found
            else "the OMS log and the paper orders agree",
        )

    def positions() -> Probe:
        found = paper_oms.position_mismatches(conn)
        return Probe(
            not found,
            f"{len(found)} position mismatch(es) against the paper book"
            if found
            else "positions agree with the paper book",
        )

    def loaded() -> Probe:
        paper_oms.build(conn, now)  # replays the whole order log: raises if it cannot
        return Probe(True, "the order log loaded")

    result = boot(
        conn, now,
        Probes(data_fresh, session, orders, positions, lambda: Probe(True, "the paper book has no broker-side cash to compare"), loaded),
        mode=State(a.mode), live_enabled=os.environ.get("ALGO_LIVE") == "1", operator=a.operator,
    )  # fmt: skip
print(f"platform state: {result.state.value}")
for f in result.failed:
    print(f"  {f}")
sys.exit(0 if result.state in TRADING else 1)
