# ruff: noqa: E501
"""The daily paper run for one user: after a session closes, decide what the account should hold and propose the orders.

It loads prices the way the backtest engine does (issuer-scoped, split-adjusted signal history through the same
Context), applies corporate actions to what the account holds, asks the account's strategy for targets, and turns the
difference from current holdings into PENDING orders sized in whole shares from the decision day's close. Nothing is filled
here: an order waits for its owner (approvals) and is booked only when filled. One run per user and day (idempotent);
a SKIPPED or ERROR run can be retried once its cause is fixed. Every run is labelled UNVALIDATED: the strategy has not
passed the project's validation gates, and these accounts can never become live trading."""

from __future__ import annotations

import bisect
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from algo.backtest.engine import SESSION_OPEN_UTC
from algo.core.clock import SimClock
from algo.core.money import snap_down
from algo.data.reader import BarReader
from algo.data.store.instruments import InstrumentRepo, NotFoundError
from algo.data.universe import Interval
from algo.live.market_calendar import windows_for
from algo.paper import book
from algo.paper.universe import FOREVER, UniverseError, current_universe
from algo.research import fundamentals_book
from algo.research.study import UniverseSpec
from algo.research.study_universe import build as segment_universe
from algo.strategies.nifty200_momentum import DataNotReady, IntervalMembership
from algo.strategies.registry import STRATEGIES
from algo.strategies.screener import ScreenerParams, ScreenerStrategy, ScreenSpec
from algo.strategy.context import Context, DataAccess, PortfolioView

BUY_BUFFER = Decimal(
    "1.01"
)  # a buy is sized as if it cost 1% more than the close: it fills at the next open, with costs
SELL_PROCEEDS = Decimal("0.99")  # and a sale is counted as bringing in 1% less
LABEL = "UNVALIDATED"
Proposal = tuple[str, int, Decimal, Decimal, str]  # side, instrument, qty, close, reason


@dataclass(frozen=True)
class Outcome:
    status: str  # PROPOSED | NO_CHANGE | SKIPPED | ERROR
    orders: list[UUID]
    detail: dict[str, Any]


def _dumps(o: Any) -> str:
    return json.dumps(o, default=str)


def _record(
    conn: psycopg.Connection,
    user_id: UUID,
    day: date,
    now: datetime,
    ident: tuple[str, str, str],
    status: str,
    detail: dict[str, Any],
    orders: list[UUID],
) -> Outcome:
    detail = {"label": LABEL, **detail}
    conn.execute(
        "INSERT INTO paper_run (user_id, decision_day, strategy_id, strategy_version, params_hash, status, detail, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (user_id, day, *ident, status, Jsonb(detail, dumps=_dumps), now),
    )
    return Outcome(status, orders, json.loads(_dumps(detail)))


def run_day(
    conn: psycopg.Connection, user_id: UUID, *, day: date, now: datetime, lake_root: Path
) -> Outcome:
    acct = book.get_account(conn, user_id)
    if acct is None:
        raise book.PaperError("no paper account for this user")
    prior = conn.execute(
        "SELECT status, detail FROM paper_run WHERE user_id=%s AND decision_day=%s", (user_id, day)
    ).fetchone()
    if prior is not None and prior[0] in ("PROPOSED", "NO_CHANGE"):
        found = conn.execute(
            "SELECT order_id FROM paper_order WHERE user_id=%s AND decision_day=%s", (user_id, day)
        ).fetchall()
        return Outcome(prior[0], [r[0] for r in found], prior[1])
    conn.execute(
        "DELETE FROM paper_run WHERE user_id=%s AND decision_day=%s", (user_id, day)
    )  # a failed or skipped run is retried
    ident = (acct["strategy_id"], "-", "-")
    if acct["strategy_id"] not in STRATEGIES:
        return _record(
            conn,
            user_id,
            day,
            now,
            ident,
            "ERROR",
            {"reason": f"unknown strategy {acct['strategy_id']}"},
            [],
        )
    if not acct["enabled"]:
        return _record(
            conn, user_id, day, now, ident, "SKIPPED", {"reason": "the account is switched off"}, []
        )
    if acct["attention"]:
        return _record(
            conn,
            user_id,
            day,
            now,
            ident,
            "SKIPPED",
            {"reason": f"paused: {acct['attention']}"},
            [],
        )
    try:
        return _decide(conn, user_id, acct, day, now, lake_root)
    except (UniverseError, DataNotReady) as e:
        return _record(conn, user_id, day, now, ident, "ERROR", {"reason": str(e)}, [])


def _next_session(conn: psycopg.Connection, day: date, now: datetime) -> tuple[datetime, datetime]:
    """(open, close) of the next trading session: orders cannot fill before it and expire when it ends. With no session
    in the next week (a long closure) they fill from now and stay open four days."""
    for k in range(1, 8):
        windows = windows_for(conn, day + timedelta(days=k))
        if windows:
            return windows[0][0], windows[-1][1]
    return now, now + timedelta(days=4)


def _traded_value(ld: Any, day: date) -> Decimal:
    """Average of close x volume over the last 20 sessions up to `day` (0 when there is no history)."""
    end = bisect.bisect_right(ld.days, day)
    rows = ld.rows[max(0, end - 20) : end]
    return sum((r[4] * r[5] for r in rows), Decimal(0)) / len(rows) if rows else Decimal(0)


def _step(repo: InstrumentRepo, iid: int, day: date) -> Decimal:
    try:
        return repo.terms_as_of(iid, day).qty_step
    except NotFoundError:
        return Decimal(1)


def _decide(
    conn: psycopg.Connection,
    user_id: UUID,
    acct: dict[str, Any],
    day: date,
    now: datetime,
    lake_root: Path,
) -> Outcome:
    strategy_cls, params_cls = STRATEGIES[acct["strategy_id"]]
    screen = acct["screen"]
    if screen is None:
        members, universe = current_universe(conn, lake_root, day, acct["universe"])
    else:  # a screener picks from market-cap classes as AMFI's list in force put each stock on this day
        members, coverage = segment_universe(
            conn, UniverseSpec(segments=screen["segments"]), day, day
        )
        universe = {
            "universe": acct["universe"],
            "segments": screen["segments"],
            "coverage": coverage,
        }
    reader = BarReader.for_env(conn)
    held = book.load(conn, user_id).quantities()
    loaded, signal = {}, {}
    for iid in sorted(set(members.ever()) | set(held)):
        ld = reader.load(iid)
        if ld.rows:
            loaded[iid], signal[iid] = ld, reader.issuer_load(iid)
    cap = acct["max_instruments"]
    if (
        cap is not None and len(members.ever()) > cap
    ):  # keep the most liquid: 20-session average traded value up to the decision day
        value = {
            iid: _traded_value(loaded[iid], day) if iid in loaded else Decimal(0)
            for iid in members.ever()
        }
        keep = sorted(members.ever(), key=lambda i: (-value[i], i))[:cap]
        members = IntervalMembership([Interval(i, FOREVER, None) for i in keep])
        universe = {**universe, "capped_to": cap}
    if screen is None:
        strategy = strategy_cls(params_cls(**acct["params"]), members)
    else:
        spec = ScreenSpec.model_validate(screen["screen"])
        filings = (  # filed ratios as known by the decision day (nothing later exists yet)
            fundamentals_book.load(conn, sorted(set(members.ever()) | set(held)), day, day)
            if spec.needs_fundamentals()
            else None
        )
        strategy = ScreenerStrategy(ScreenerParams(**acct["params"]), members, spec, filings)
    ident = (strategy.id, strategy.version, strategy.params_hash)
    book.apply_actions(
        conn, user_id, {i: loaded[i].recs for i in held if i in loaded}, through=day, now=now
    )
    ledger = book.load(conn, user_id)
    held = ledger.quantities()
    close_on: dict[int, Decimal] = {}  # instruments with a bar on the decision day
    last_close: dict[int, Decimal] = {}
    for iid, ld in loaded.items():
        at = bisect.bisect_right(ld.days, day) - 1
        if at >= 0:
            last_close[iid] = ld.rows[at][4]
            if ld.days[at] == day:
                close_on[iid] = ld.rows[at][4]
    marks = {iid: last_close.get(iid, ledger.cost_basis(iid) / q) for iid, q in held.items()}
    equity = ledger.equity(marks)
    conn.execute(
        "INSERT INTO paper_equity (user_id, day, equity, cash) VALUES (%s,%s,%s,%s) ON CONFLICT (user_id, day) DO UPDATE SET equity=EXCLUDED.equity, cash=EXCLUDED.cash",
        (user_id, day, equity, ledger.cash),
    )

    clock = SimClock(datetime.combine(day, SESSION_OPEN_UTC, UTC) + reader.visible_after)
    ctx = Context(
        clock,
        DataAccess(signal, clock, strategy.requirements().adjust),
        PortfolioView.of(ledger.cash, held, equity),
        "research",
    )
    targets = strategy.on_schedule(ctx)
    audit = strategy.audit[-1] if strategy.audit else {}
    base = {"universe": universe, "audit": audit, "equity": equity, "cash": ledger.cash}
    if targets is None:
        return _record(
            conn,
            user_id,
            day,
            now,
            ident,
            "NO_CHANGE",
            {**base, "reason": "the strategy kept its targets"},
            [],
        )

    repo = InstrumentRepo(conn)
    exits, entries = audit.get("exits", {}), set(audit.get("entries", []))
    entry_reason = audit.get("entry_reason", "entry: oversold in an uptrend")
    sells: list[Proposal] = []
    buys: list[Proposal] = []
    for iid in sorted(set(targets) | set(held)):
        px = close_on.get(iid)
        if px is None:
            continue  # no bar for the decision day: it can be neither sized nor traded
        delta = snap_down(
            targets.get(iid, Decimal(0)) * equity / px, _step(repo, iid, day)
        ) - held.get(iid, Decimal(0))
        if delta < 0:
            sells.append(
                (
                    "SELL",
                    iid,
                    min(-delta, held[iid]),
                    px,
                    f"exit: {exits[iid]}" if iid in exits else "reduce to the target weight",
                )
            )
        elif delta > 0:
            buys.append(
                (
                    "BUY",
                    iid,
                    delta,
                    px,
                    entry_reason if iid in entries else "increase to the target weight",
                )
            )
    available = ledger.cash + sum((q * px for _, _, q, px, _ in sells), Decimal(0)) * SELL_PROCEEDS
    proposals, skipped_for_cash = list(sells), []
    for side, iid, qty, px, reason in buys:  # in instrument order: deterministic
        qty = min(qty, snap_down(available / (px * BUY_BUFFER), _step(repo, iid, day)))
        if qty <= 0:
            skipped_for_cash.append(iid)
            continue
        available -= qty * px * BUY_BUFFER
        proposals.append((side, iid, qty, px, reason))
    if not proposals:
        return _record(
            conn,
            user_id,
            day,
            now,
            ident,
            "NO_CHANGE",
            {
                **base,
                "reason": "holdings already match the targets",
                "skipped_for_cash": skipped_for_cash,
            },
            [],
        )
    conn.execute(
        "UPDATE paper_order SET status='EXPIRED' WHERE user_id=%s AND status='PENDING' AND decision_day < %s",
        (user_id, day),
    )
    not_before, expires = _next_session(conn, day, now)
    ids: list[UUID] = []
    for side, iid, qty, px, reason in proposals:
        row = conn.execute(
            "INSERT INTO paper_order (user_id, decision_day, instrument_id, side, qty, ref_price, reason, created_at, not_before, expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING order_id",
            (user_id, day, iid, side, qty, px, reason, now, not_before, expires),
        ).fetchone()
        assert row is not None
        ids.append(row[0])
    return _record(
        conn,
        user_id,
        day,
        now,
        ident,
        "PROPOSED",
        {**base, "orders": len(ids), "skipped_for_cash": skipped_for_cash},
        ids,
    )
