# ruff: noqa: E501
"""The live process (TODO 5.3): recovers the order log on start, then every few seconds takes the kill switch from the database, reconciles the OMS
with the Kite account once a minute in session and once after the close, and beats as process `live` (add `live` to ALGO_EXPECT_PROCESSES to be alerted).
It exits 0 at once on a closed day and 10 minutes after the last session window ends (the final reconcile pass runs inside that).
It does not decide orders: proposals come from the daily paper/live runner and your approval; this process sends what is approved. It refuses to start unless the live gate is open
(ALGO_LIVE=1, the strategy in the LIVE stage, a valid Kite session of this user, every regulatory rule recorded and recently verified): exit 3, with the reasons.
Never touches the owner's own holdings: the OMS runs with own_positions_only.
usage: live_process.py --user-id UUID [--db URL] [--every 5]   (the person: their LIVE account says which strategy runs and with what capital)"""

import argparse
import os
import signal
import socket
import sys
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

import psycopg

from algo.core.clock import SystemClock
from algo.data.providers.kite_session import urllib_http
from algo.execution import regulatory
from algo.execution.event_store import DbStore
from algo.execution.kite_account import KiteAccount
from algo.execution.kite_broker import KiteBroker
from algo.execution.live_gate import LiveRefused, open_gate
from algo.execution.oms import Oms
from algo.live.market_calendar import IST, windows_for
from algo.live.process import LiveProcess
from algo.paper import book
from algo.paper.jobs import cost_policy
from algo.portal.crypto import KeyRing
from algo.portal.kite_vault import user_credentials
from algo.risk import store as risk_store
from algo.risk.engine import RiskEngine
from algo.risk.limits import Limits
from algo.strategy import stage

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--user-id", required=True)
ap.add_argument("--every", type=float, default=5.0, help="seconds between ticks")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")

clock = SystemClock()
with psycopg.connect(a.db, autocommit=True) as conn:
    now = clock.now()
    windows = windows_for(conn, now.astimezone(IST).date())
    if not windows:
        print("no trading session today: nothing to do", flush=True)
        sys.exit(0)
    until = windows[-1][1] + timedelta(
        minutes=10
    )  # the final pass after the close runs inside this
    acct = book.get_account(conn, book.account_key(UUID(a.user_id), "LIVE"))
    if acct is None or acct["config_id"] is None:
        print("this person has no live account with a strategy yet: create one on the Trading page")
        sys.exit(3)
    creds = user_credentials(conn, KeyRing.from_env(os.environ), user_id=UUID(a.user_id), now=now)
    try:
        gate = open_gate(
            os.environ,
            stage.current(conn, acct["config_id"]),
            creds is not None,
            regulatory.check(conn, now.date()),
        )
    except LiveRefused as e:
        print(e)
        sys.exit(3)
    assert creds is not None  # the gate is open only with a valid session
    symbols = {
        int(i): s
        for i, s in conn.execute(
            "SELECT instrument_id, tradingsymbol FROM kite_instrument WHERE instrument_id IS NOT NULL AND active"
        ).fetchall()
    }
    broker = KiteBroker(creds[0], creds[1], urllib_http, symbols, gate=gate)
    oms = Oms(
        broker,
        RiskEngine(Limits(), risk_store.load(conn)),
        clock,
        store=DbStore(conn),
        own_positions_only=True,
    )
    proc = LiveProcess(
        oms,
        KiteAccount(creds[0], creds[1], urllib_http),
        symbols,
        clock,
        conn,
        host=socket.gethostname(),
        pid=os.getpid(),
        cost=cost_policy(conn),
    )
    stopping = False

    def stop(*_: object) -> None:
        global stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    proc.start()
    print(f"{datetime.now(UTC):%H:%M:%S}Z live process started", flush=True)
    while not stopping and clock.now() < until:
        for m in proc.tick():
            print(f"  {m.kind} {m.client_order_id} {m.detail}", flush=True)
        time.sleep(a.every)
    proc.stop()
