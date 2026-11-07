"""Daily event-driven backtest (long-only target weights).
Rules (spec section 10): decide on the close of day t, execute at the OPEN of t+1; execution and
accounting use RAW prices only (adjusted prices are for signals); fills capped at a share of the
bar's volume (remainder cancels); positions follow corporate actions (bonus/split share counts,
cash dividends); held positions that pass through an action the accounting cannot model are
reported, never hidden. Costs here are a flagged PLACEHOLDER until the versioned cost schedule."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal

import psycopg

from algo.backtest.metrics import metrics
from algo.core.clock import SimClock
from algo.core.money import snap_down
from algo.data.adjust.factors import ActionRecord
from algo.data.reader import BarReader, UnadjustableError
from algo.data.store.instruments import InstrumentRepo, NotFoundError
from algo.strategy.base import Mode, Strategy, Targets
from algo.strategy.context import Context, DataAccess, PortfolioView

BPS = Decimal(10000)
SESSION_OPEN_UTC = time(3, 45)  # 09:15 IST
EPS = Decimal("1e-9")


class InvalidTargets(Exception):
    pass


@dataclass(frozen=True)
class CostModel:
    name: str
    commission_bps: Decimal
    slippage_bps: Decimal
    placeholder: bool  # True until the versioned cost_schedule replaces flat bps


PLACEHOLDER_COSTS = CostModel("flat-bps-placeholder", Decimal(10), Decimal(5), True)


@dataclass(frozen=True)
class BacktestConfig:
    start: date
    end: date
    initial_cash: Decimal
    mode: Mode = Mode.RESEARCH
    cost: CostModel = PLACEHOLDER_COSTS
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
    cost: Decimal


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

    @property
    def accounting_complete(self) -> bool:
        return not self.unmodelled

    @property
    def result_hash(self) -> str:
        body = {
            "equity": [[str(d), str(v)] for d, v in self.equity],
            "trades": [[t.seq, str(t.day), t.instrument_id, t.side, str(t.qty), str(t.price),
                        str(t.cost)] for t in self.trades],
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
    days = sorted({d for ld in loaded.values() for d in ld.days if cfg.start <= d <= cfg.end})

    # --- the loop -----------------------------------------------------------------------------
    pos: dict[int, Decimal] = {}
    last_close: dict[int, Decimal] = {}
    targets: Targets = {}
    rebalance, prev_day, seq = False, None, 0
    started = False
    for i, day in enumerate(days):
        # 1. corporate actions with ex-date since the previous session
        for iid in loaded:
            held = pos.get(iid, Decimal(0))
            if held == 0:
                continue
            for a in acts[iid]:
                if (prev_day is not None and a.ex_date <= prev_day) or a.ex_date > day:
                    continue
                if a.kind in ("bonus", "split") and a.status == "ok" and a.num and a.den:
                    pos[iid] = pos[iid] * a.num / a.den
                elif a.kind == "dividend" and a.status == "ok" and a.amount:
                    cash += held * a.amount
                    res.dividends_received += held * a.amount
                else:
                    res.unmodelled.append({"instrument_id": iid, "ex_date": str(a.ex_date),
                                           "kind": a.kind, "qty": str(held)})  # fmt: skip
        # 2. execute the previous close's decision at today's open (RAW prices)
        if rebalance:
            rebalance = False
            tradable = [iid for iid in loaded if day in px[iid]]
            open_ = {iid: px[iid][day][0] for iid in tradable}
            equity_open = cash + sum(
                (q * open_.get(iid, last_close.get(iid, Decimal(0))) for iid, q in pos.items()),
                Decimal(0),
            )
            want = {
                iid: snap_down(targets.get(iid, Decimal(0)) * equity_open / open_[iid], step[iid])
                for iid in tradable
                if iid in targets or pos.get(iid, 0) != 0
            }
            cap = {
                iid: snap_down(cfg.max_participation * px[iid][day][2], step[iid]) for iid in want
            }
            for side in ("SELL", "BUY"):  # sells first: they fund the buys
                for iid in sorted(want):
                    cur = pos.get(iid, Decimal(0))
                    delta = want[iid] - cur
                    if (side == "SELL") != (delta < 0) or delta == 0:
                        continue
                    sign = 1 if side == "BUY" else -1
                    price = open_[iid] * (1 + sign * cfg.cost.slippage_bps / BPS)
                    qty = min(abs(delta), cap[iid])
                    if side == "BUY":
                        affordable = snap_down(
                            cash / (price * (1 + cfg.cost.commission_bps / BPS)), step[iid]
                        )
                        qty = min(qty, affordable)
                    if qty <= 0:
                        continue
                    value = qty * price
                    cost = value * cfg.cost.commission_bps / BPS
                    cash += -(value + cost) if side == "BUY" else value - cost
                    pos[iid] = cur + sign * qty
                    seq += 1
                    res.trades.append(Trade(seq, day, iid, side, qty, price, cost))
        # 3. mark to market at the close (RAW)
        for iid in loaded:
            if day in px[iid]:
                last_close[iid] = px[iid][day][1]
        equity = cash + sum((q * last_close[iid] for iid, q in pos.items()), Decimal(0))
        res.equity.append((day, equity))
        # 4. decide on this close; the order goes in at the next open
        if i < len(days) - 1:
            clock.advance_to(datetime.combine(day, SESSION_OPEN_UTC, UTC) + reader.visible_after)
            ctx = Context(
                clock,
                DataAccess(loaded, clock, req.adjust),
                PortfolioView.of(cash, pos, equity),
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
    res.final_cash, res.final_positions = cash, {k: v for k, v in pos.items() if v != 0}
    res.metrics = metrics(res.equity)
    return res
