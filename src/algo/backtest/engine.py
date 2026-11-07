"""Daily event-driven backtest (long-only target weights).
Rules (spec section 10): decide on the close of day t, execute at the OPEN of t+1; execution and
accounting use RAW prices only (adjusted prices are for signals); fills capped at a share of the
bar's volume (remainder cancels); positions follow corporate actions (bonus/split share counts,
cash dividends); held positions that pass through an action the accounting cannot model are
reported, never hidden. Costs here are a flagged PLACEHOLDER until the versioned cost schedule."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal
from functools import partial
from typing import Any

import psycopg

from algo.backtest.costs.calculator import Charges
from algo.backtest.costs.policy import (
    PLACEHOLDER_COSTS,
    CostPolicy,
    Liquidity,
)
from algo.backtest.metrics import metrics
from algo.core.clock import SimClock
from algo.core.money import snap_down
from algo.data.adjust.factors import ActionRecord
from algo.data.reader import BarReader, UnadjustableError
from algo.data.store.instruments import InstrumentRepo, NotFoundError
from algo.ledger.ledger import Ledger
from algo.strategy.base import Mode, Strategy, Targets
from algo.strategy.context import Context, DataAccess, PortfolioView

BPS = Decimal(10000)
SESSION_OPEN_UTC = time(3, 45)  # 09:15 IST
EPS = Decimal("1e-9")


class InvalidTargets(Exception):
    pass


@dataclass(frozen=True)
class BacktestConfig:
    start: date
    end: date
    initial_cash: Decimal
    mode: Mode = Mode.RESEARCH
    cost: CostPolicy = PLACEHOLDER_COSTS
    max_participation: Decimal = Decimal("0.05")  # share of the bar's volume one order may take
    max_weight: Decimal = Decimal(1)


@dataclass(frozen=True)
class Trade:
    seq: int
    day: date
    instrument_id: int
    side: str
    qty: Decimal
    price: Decimal
    cost: Decimal  # total charges, rupees
    slippage_bps: Decimal
    charges: Charges  # the itemised, explained charge lines


def _event(iid: int, a: ActionRecord) -> dict[str, object]:
    factor = str(a.den / a.num) if a.kind == "resolved" and a.num and a.den else None
    return {"instrument_id": iid, "ex_date": str(a.ex_date), "kind": a.kind, "status": a.status,
            "factor": factor}  # fmt: skip


@dataclass
class RunResult:
    strategy_id: str
    strategy_version: str
    params_json: str
    params_hash: str
    code_version: str
    config: BacktestConfig
    equity: list[tuple[date, Decimal]] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    metrics: dict[str, float | None] = field(default_factory=dict)
    adjustment_versions: dict[int, str] = field(default_factory=dict)
    provisional: list[dict[str, object]] = field(default_factory=list)
    unapplied: list[dict[str, object]] = field(default_factory=list)
    blocked: dict[int, str] = field(default_factory=dict)
    unmodelled: list[dict[str, object]] = field(default_factory=list)
    dividends_received: Decimal = Decimal(0)
    final_cash: Decimal = Decimal(0)
    final_positions: dict[int, Decimal] = field(default_factory=dict)
    ledger: Ledger | None = None  # the canonical books: cash, positions, fees, P&L
    cost_info: dict[str, object] = field(default_factory=dict)  # model + schedules actually used
    schedules_used: dict[str, tuple[str, str]] = field(
        default_factory=dict
    )  # id -> (version, status)
    note_charges: list[dict[str, object]] = field(default_factory=list)  # contract-note top-ups
    reconciliation: list[str] = field(default_factory=list)  # empty = the ledger agrees with itself
    pnl: dict[str, str] = field(
        default_factory=dict
    )  # realized / unrealized / dividends / fees / net

    @property
    def ledger_reconciled(self) -> bool:
        return self.ledger is not None and not self.reconciliation

    @property
    def accounting_complete(self) -> bool:
        return not self.unmodelled

    @property
    def result_hash(self) -> str:
        body = {
            "equity": [[str(d), str(v)] for d, v in self.equity],
            "trades": [[t.seq, str(t.day), t.instrument_id, t.side, str(t.qty), str(t.price),
                        str(t.slippage_bps),
                        str(t.cost)] for t in self.trades],
            "ledger": [
                [e.seq, str(e.day), e.ledger, e.kind, e.instrument_id, str(e.qty),
                 str(e.amount), e.ref]
                for e in (self.ledger.entries if self.ledger else [])
            ],
        }  # fmt: skip
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def _validate(targets: Targets, allowed: set[int], cfg: BacktestConfig) -> None:
    for iid, w in targets.items():
        if iid not in allowed:
            raise InvalidTargets(f"instrument {iid} is not in the (unblocked) universe")
        if w < 0:
            raise InvalidTargets("long-only: negative weight")
        if w > cfg.max_weight:
            raise InvalidTargets(f"weight {w} exceeds max_weight {cfg.max_weight}")
    if sum(targets.values(), Decimal(0)) > 1 + EPS:
        raise InvalidTargets("target weights sum to more than 100% of equity")


def _liquidity(rows: list[tuple[Any, ...]], idx: int, volume: Decimal) -> Liquidity:
    """Recent range and traded value from the 20 sessions BEFORE the execution bar."""
    prev = rows[max(0, idx - 20) : idx]
    if not prev:
        return Liquidity(volume, Decimal(0), None)
    n = Decimal(len(prev))
    range_bps = sum(((r[2] - r[3]) / r[4] * BPS for r in prev), Decimal(0)) / n
    adv = sum((r[4] * r[5] for r in prev), Decimal(0)) / n
    return Liquidity(volume, range_bps, adv)


def _all_in(
    cost: CostPolicy, day: date, side: str, reference: Decimal, liq: Liquidity, qty: Decimal
) -> Decimal:
    """Total rupees an order of `qty` costs: shares at the slipped fill price plus all charges."""
    fill, _ = cost.fill(side, reference, qty, liq)
    return qty * fill + cost.charges(day, side, qty, fill).total


def _max_affordable(
    upper: Decimal, step: Decimal, cash: Decimal, total_cost: Callable[[Decimal], Decimal]
) -> Decimal:
    """Largest multiple of `step` up to `upper` whose all-in cost fits in `cash`. All-in cost grows
    with size (fill price rises with participation, charges rise with value), so bisect."""
    lo, hi = 0, int(upper / step)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if total_cost(step * mid) <= cash:
            lo = mid
        else:
            hi = mid - 1
    return step * lo


def run_backtest(
    conn: psycopg.Connection,
    strategy: Strategy,
    cfg: BacktestConfig,
    *,
    code_version: str = "unversioned",
) -> RunResult:
    reader, strict = BarReader(conn), cfg.mode is Mode.STRICT
    req = strategy.requirements()
    clock = SimClock(datetime.combine(cfg.start, time(0), UTC))
    res = RunResult(strategy.id, strategy.version, strategy.params.model_dump_json(),
                    strategy.params_hash, code_version, cfg)  # fmt: skip
    cash = cfg.initial_cash

    # --- universe + preflight: which instruments may be used, and on what data -----------------
    ctx0 = Context(
        clock, DataAccess({}, clock, req.adjust), PortfolioView.of(cash, {}, cash), cfg.mode.value
    )
    loaded = {}
    for iid in dict.fromkeys(strategy.universe(ctx0)):
        ld = reader.load(iid, strict=strict)
        try:
            h = ld.history(cfg.start, cfg.end, adjust=req.adjust)
        except UnadjustableError as e:
            res.blocked[iid] = str(e)  # strict: unresolved / provisional actions block the name
            continue
        if not h.bars:
            res.blocked[iid] = "no bars in range"
            continue
        loaded[iid] = ld
        res.adjustment_versions[iid] = h.adjustment_version
        res.provisional += [_event(iid, p) for p in h.provisional]
        res.unapplied += [_event(iid, u) for u in h.unapplied]

    repo, step = InstrumentRepo(conn), {}
    for iid in loaded:
        try:
            step[iid] = repo.terms_as_of(iid, cfg.start).qty_step
        except NotFoundError:
            step[iid] = Decimal(1)
    px = {
        iid: {
            d: (r[1], r[4], r[5]) for d, r in zip(ld.days, ld.rows, strict=True)
        }  # open, close, vol
        for iid, ld in loaded.items()
    }
    acts = {iid: sorted(ld.recs, key=lambda a: a.ex_date) for iid, ld in loaded.items()}
    dayidx = {iid: {d: i for i, d in enumerate(ld.days)} for iid, ld in loaded.items()}
    days = sorted({d for ld in loaded.values() for d in ld.days if cfg.start <= d <= cfg.end})

    # --- the loop -----------------------------------------------------------------------------
    ledger = Ledger(cfg.initial_cash, cfg.start)
    last_close: dict[int, Decimal] = {}
    targets: Targets = {}
    rebalance, prev_day, seq = False, None, 0
    started = False
    for i, day in enumerate(days):
        # 1. corporate actions with ex-date since the previous session
        for iid in loaded:
            if ledger.qty(iid) == 0:
                continue
            for k, a in enumerate(acts[iid]):
                if (prev_day is not None and a.ex_date <= prev_day) or a.ex_date > day:
                    continue
                ref = f"action:{iid}:{a.ex_date}:{a.kind}:{k}"
                if a.kind in ("bonus", "split") and a.status == "ok" and a.num and a.den:
                    ledger.apply_split(day, iid, a.num, a.den, ref)
                elif a.kind == "dividend" and a.status == "ok" and a.amount:
                    res.dividends_received += ledger.credit_dividend(day, iid, a.amount, ref)
                else:
                    ledger.flag_unmodelled(day, iid, a.kind, ref)
                    res.unmodelled.append({"instrument_id": iid, "ex_date": str(a.ex_date),
                                           "kind": a.kind,
                                           "qty": str(ledger.qty(iid))})  # fmt: skip
        # 2. execute the previous close's decision at today's open (RAW prices)
        if rebalance:
            rebalance = False
            tradable = [iid for iid in loaded if day in px[iid]]
            open_ = {iid: px[iid][day][0] for iid in tradable}
            marks = {
                iid: open_.get(iid, last_close.get(iid, Decimal(0))) for iid in ledger.quantities()
            }
            equity_open = ledger.equity(marks)
            want = {
                iid: snap_down(targets.get(iid, Decimal(0)) * equity_open / open_[iid], step[iid])
                for iid in tradable
                if iid in targets or ledger.qty(iid) != 0
            }
            cap = {
                iid: snap_down(cfg.max_participation * px[iid][day][2], step[iid]) for iid in want
            }
            day_brokerage, day_fills = Decimal(0), 0
            for side in ("SELL", "BUY"):  # sells first: they fund the buys
                for iid in sorted(want):
                    delta = want[iid] - ledger.qty(iid)
                    if (side == "SELL") != (delta < 0) or delta == 0:
                        continue
                    upper = min(abs(delta), cap[iid])
                    liq = _liquidity(loaded[iid].rows, dayidx[iid][day], px[iid][day][2])

                    qty = (
                        _max_affordable(
                            upper,
                            step[iid],
                            ledger.cash,
                            partial(_all_in, cfg.cost, day, side, open_[iid], liq),
                        )
                        if side == "BUY"
                        else upper
                    )
                    if qty <= 0:
                        continue
                    price, bps = cfg.cost.fill(side, open_[iid], qty, liq)
                    ch = cfg.cost.charges(day, side, qty, price)
                    res.schedules_used[ch.schedule_id] = (ch.schedule_version, ch.schedule_status)
                    seq += 1
                    post = ledger.buy if side == "BUY" else ledger.sell
                    post(
                        day, iid, qty, price, ch.amount("COMMISSION"), f"trade:{seq}",
                        charges=[
                            (ln.type, ln.amount) for ln in ch.lines if ln.type != "COMMISSION"
                        ],
                    )  # fmt: skip
                    res.trades.append(Trade(seq, day, iid, side, qty, price, ch.total, bps, ch))
                    day_brokerage += ch.amount("BROKERAGE")
                    day_fills += 1
            if day_fills:  # one contract note per trading day
                top_up = cfg.cost.note_shortfall(day, day_brokerage)
                if top_up > 0:
                    ledger.post_charges(day, [("BROKERAGE", top_up)], f"note:{day}")
                    res.note_charges.append(
                        {"day": str(day), "type": "BROKERAGE", "amount": str(top_up)}
                    )
        # 3. mark to market at the close (RAW)
        for iid in loaded:
            if day in px[iid]:
                last_close[iid] = px[iid][day][1]
        equity = ledger.equity(last_close)
        res.equity.append((day, equity))
        # 4. decide on this close; the order goes in at the next open
        if i < len(days) - 1:
            clock.advance_to(datetime.combine(day, SESSION_OPEN_UTC, UTC) + reader.visible_after)
            ctx = Context(
                clock,
                DataAccess(loaded, clock, req.adjust),
                PortfolioView.of(ledger.cash, ledger.quantities(), equity),
                cfg.mode.value,
            )
            if not started:
                strategy.on_start(ctx)
                started = True
            new = strategy.on_schedule(ctx)
            if new is not None:
                _validate(new, set(loaded), cfg)
                targets, rebalance = dict(new), True
        prev_day = day
    res.final_cash, res.final_positions = ledger.cash, ledger.quantities()
    res.ledger = ledger
    p = ledger.pnl(last_close)
    res.pnl = {"realized": str(p.realized), "unrealized": str(p.unrealized),
               "dividends": str(p.dividends), "fees": str(p.fees), "net": str(p.net)}  # fmt: skip
    res.reconciliation = ledger.reconcile(last_close)
    res.cost_info = {
        **cfg.cost.describe(),
        "schedules_used": [
            {"id": i, "version": v, "status": st}
            for i, (v, st) in sorted(res.schedules_used.items())
        ],
        "unverified_schedules": any(
            st not in ("verified", "placeholder") for _, st in res.schedules_used.values()
        ),
    }
    res.metrics = metrics(res.equity)
    return res
