"""Persist a backtest with everything needed to reproduce it and to judge what it proves."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

from algo.backtest.engine import RunResult
from algo.core.clock import require_utc
from algo.strategy.lifecycle import RunSummary


def _j(v: object) -> Jsonb:
    return Jsonb(json.loads(json.dumps(v, default=str)))


def save_run(conn: psycopg.Connection, r: RunResult, now: datetime) -> int:
    cfg = r.config
    with conn.transaction():
        cols = (
            "strategy_id,strategy_version,params,params_hash,code_version,reader_mode,config,"
            "cost_model,adjustment_versions,provisional_events,unapplied_events,blocked_instruments,"
            "unmodelled_events,accounting_complete,dividends_received,metrics,result_hash,created_at"
        )
        values = (
            r.strategy_id, r.strategy_version, Jsonb(json.loads(r.params_json)), r.params_hash,
            r.code_version, cfg.mode.value, _j({**asdict(cfg), "cost": None}), _j(asdict(cfg.cost)),
            _j(r.adjustment_versions), _j(r.provisional), _j(r.unapplied), _j(r.blocked),
            _j(r.unmodelled), r.accounting_complete, r.dividends_received, _j(r.metrics),
            r.result_hash, require_utc(now),
        )  # fmt: skip
        row = conn.execute(
            f"INSERT INTO backtest_run ({cols}) VALUES ({','.join(['%s'] * 18)}) RETURNING run_id",
            values,
        ).fetchone()
        assert row is not None
        run_id = row[0]
        cur = conn.cursor()
        cur.executemany(
            "INSERT INTO backtest_trade VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            [
                (run_id, t.seq, t.day, t.instrument_id, t.side, t.qty, t.price, t.cost)
                for t in r.trades
            ],
        )
        cur.executemany(
            "INSERT INTO backtest_equity VALUES (%s,%s,%s)", [(run_id, d, v) for d, v in r.equity]
        )
    return int(run_id)


def summary(
    conn: psycopg.Connection, run_id: int, *, validation_protocol_passed: bool = False
) -> RunSummary:
    row = conn.execute(
        "SELECT reader_mode, jsonb_array_length(provisional_events), "
        "jsonb_array_length(unapplied_events), accounting_complete, "
        "(cost_model->>'placeholder')::boolean FROM backtest_run WHERE run_id=%s",
        (run_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"no backtest run {run_id}")
    return RunSummary(row[0], row[1], row[2], row[3], row[4], validation_protocol_passed)
