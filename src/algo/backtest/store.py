"""Persist a backtest with everything needed to reproduce it and to judge what it proves."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

from algo.backtest.engine import RunResult, Trade
from algo.backtest.validation.registry import validation_passed
from algo.core.clock import require_utc
from algo.strategy.lifecycle import RunSummary


def _j(v: object) -> Jsonb:
    return Jsonb(json.loads(json.dumps(v, default=str)))


def _charges_json(t: Trade) -> Jsonb:
    """The itemised charge lines of one trade, with the exact schedule that produced them."""
    ch = t.charges
    return Jsonb(
        {
            "schedule_id": ch.schedule_id,
            "schedule_version": ch.schedule_version,
            "schedule_status": ch.schedule_status,
            "lines": [
                {
                    "type": ln.type,
                    "amount": str(ln.amount),
                    "basis_value": None if ln.basis_value is None else str(ln.basis_value),
                    "formula": ln.formula,
                    "rounding": ln.rounding,
                    "source": ln.source,
                }
                for ln in ch.lines
            ],
        }
    )


def save_run(conn: psycopg.Connection, r: RunResult, now: datetime) -> int:
    cfg = r.config
    with conn.transaction():
        cols = (
            "strategy_id,strategy_version,params,params_hash,code_version,reader_mode,config,"
            "cost_model,adjustment_versions,provisional_events,unapplied_events,blocked_instruments,"
            "unmodelled_events,accounting_complete,dividends_received,metrics,result_hash,created_at,"
            "ledger_reconciled,reconciliation,pnl"
        )
        values = (
            r.strategy_id, r.strategy_version, Jsonb(json.loads(r.params_json)), r.params_hash,
            r.code_version, cfg.mode.value, _j({**asdict(cfg), "cost": None}), _j(r.cost_info),
            _j(r.adjustment_versions), _j(r.provisional), _j(r.unapplied), _j(r.blocked),
            _j(r.unmodelled), r.accounting_complete, r.dividends_received, _j(r.metrics),
            r.result_hash, require_utc(now),
            r.ledger_reconciled, _j(r.reconciliation), _j(r.pnl),
        )  # fmt: skip
        row = conn.execute(
            f"INSERT INTO backtest_run ({cols}) VALUES ({','.join(['%s'] * 21)}) RETURNING run_id",
            values,
        ).fetchone()
        assert row is not None
        run_id = row[0]
        cur = conn.cursor()
        cur.executemany(
            "INSERT INTO backtest_trade (run_id,seq,day,instrument_id,side,qty,price,cost,"
            "slippage_bps,charges) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [
                (
                    run_id,
                    t.seq,
                    t.day,
                    t.instrument_id,
                    t.side,
                    t.qty,
                    t.price,
                    t.cost,
                    t.slippage_bps,
                    _charges_json(t),
                )
                for t in r.trades
            ],  # fmt: skip
        )
        cur.executemany(
            "INSERT INTO backtest_equity VALUES (%s,%s,%s)", [(run_id, d, v) for d, v in r.equity]
        )
        cur.executemany(
            "INSERT INTO backtest_ledger VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [
                (run_id, e.seq, e.day, e.ledger, e.kind, e.instrument_id, e.qty, e.amount, e.ref)
                for e in (r.ledger.entries if r.ledger else [])
            ],
        )
    return int(run_id)


def summary(
    conn: psycopg.Connection, run_id: int, *, validation_protocol_passed: bool | None = None
) -> RunSummary:
    row = conn.execute(
        "SELECT reader_mode, jsonb_array_length(provisional_events), "
        "jsonb_array_length(unapplied_events), accounting_complete, "
        "(cost_model->>'placeholder')::boolean, ledger_reconciled, "
        "COALESCE((cost_model->>'unverified_schedules')::boolean, false), "
        "COALESCE((cost_model->>'zero_slippage')::boolean, false) "
        "FROM backtest_run WHERE run_id=%s",
        (run_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"no backtest run {run_id}")
    if (
        validation_protocol_passed is None
    ):  # default: only a stored, passing, confirmed report counts
        validation_protocol_passed = validation_passed(conn, run_id)
    return RunSummary(
        row[0], row[1], row[2], row[3], row[4], validation_protocol_passed, row[5], row[6], row[7]
    )
