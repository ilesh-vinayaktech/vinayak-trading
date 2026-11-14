# ruff: noqa: E501
"""The scheduled paper cycle. `run_accounts` decides for every enabled account on the newest session (run after the evening data jobs;
the readiness gate stops it on data that cannot support a decision); `process_orders` fills approved orders at the next live open and
expires the rest (run every few minutes while the market is open). Both are safe to repeat."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import psycopg

from algo.api import freshness
from algo.backtest.costs import schedule_store
from algo.backtest.costs.policy import CostPolicy, ScheduleCosts
from algo.backtest.costs.slippage import SlippageModel
from algo.data.readiness import holidays
from algo.paper import orders
from algo.paper.runner import Outcome, SandboxConfig, run_day

BROKER = "zerodha"
SLIPPAGE_BPS = Decimal(
    5
)  # the studies' default base slippage; paper fills use a flat figure, not the participation model
ALLOWED_COSTS = (
    "verified",
    "extracted_unverified",
    "assumed_backfill",
)  # the same schedules the studies price with


def cost_policy(conn: psycopg.Connection) -> CostPolicy:
    return ScheduleCosts(
        schedule_store.load_book(conn, BROKER, ALLOWED_COSTS),
        SlippageModel(
            base_bps=SLIPPAGE_BPS,
            participation_bps_per_pct=Decimal(5),
            volatility_fraction=Decimal(0),
        ),
        product="DELIVERY",
        name=f"{BROKER}-delivery",
    )


def decision_day(conn: psycopg.Connection, now: datetime) -> date | None:
    """The newest session with bars, provided that is the session whose file should be published by now; otherwise None."""
    row = conn.execute(
        "SELECT max((ts AT TIME ZONE 'Asia/Kolkata')::date) FROM bar_1d WHERE source='nse'"
    ).fetchone()
    newest = None if row is None else row[0]
    if newest is None:
        return None
    verdict = freshness.assess(newest, now, frozenset(holidays(conn)))
    return newest if verdict["status"] == "CURRENT" else None


def run_accounts(
    conn: psycopg.Connection,
    now: datetime,
    *,
    lake_root: Path,
    day: date | None = None,
    sandbox: SandboxConfig | None = None,
) -> list[tuple[UUID, Outcome]]:
    """One decision per enabled account that is not waiting on a person. `day` defaults to the newest session (None: nothing to decide)."""
    decide_on = day or decision_day(conn, now)
    if decide_on is None:
        return []
    users = [
        r[0]
        for r in conn.execute(
            "SELECT user_id FROM paper_account WHERE enabled AND attention IS NULL ORDER BY created_at, user_id"
        )
    ]
    return [
        (u, run_day(conn, u, day=decide_on, now=now, lake_root=lake_root, sandbox=sandbox))
        for u in users
    ]


def process_orders(conn: psycopg.Connection, now: datetime) -> orders.FillReport:
    """Expire what has run out of time, then fill what can fill. Waiting orders (no live price yet) are left for the next tick."""
    orders.expire_due(conn, now)
    return orders.fill_due(conn, now, cost=cost_policy(conn), slippage_bps=SLIPPAGE_BPS)
