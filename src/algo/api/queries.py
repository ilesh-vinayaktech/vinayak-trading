"""Read-only SQL behind the API. Every value is returned as the database holds it: prices and
levels as strings (never floats), dates as ISO strings. Nothing is calculated here that a backend
service already owns (adjustment, eligibility, metrics)."""

from __future__ import annotations

from datetime import date
from typing import Any

import psycopg

from algo.data.benchmark import dataset_hash, levels
from algo.data.reader import IST, BarReader

IST_DAY = "(ts AT TIME ZONE 'Asia/Kolkata')::date"


def _iso(v: Any) -> Any:
    return v.isoformat() if hasattr(v, "isoformat") else v


def _rows(conn: psycopg.Connection, sql: str, args: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    return conn.execute(sql, args).fetchall()


def _one(conn: psycopg.Connection, sql: str, args: tuple[Any, ...] = ()) -> tuple[Any, ...]:
    row = conn.execute(sql, args).fetchone()
    assert row is not None
    return row


def data_health(conn: psycopg.Connection) -> dict[str, Any]:
    bars = _one(conn, "SELECT count(*) FROM bar_1d")[0]
    first, last = _one(conn, "SELECT min(ts), max(ts) FROM bar_1d")
    with_bars = _one(
        conn,
        "SELECT count(*) FROM instrument i WHERE EXISTS"
        " (SELECT 1 FROM bar_1d b WHERE b.instrument_id = i.instrument_id)",
    )[0]
    per_day = _rows(
        conn,
        f"SELECT {IST_DAY} d, count(*) FROM bar_1d GROUP BY 1 ORDER BY 1 DESC LIMIT 2",
    )
    latest_n = per_day[0][1] if per_day else 0
    previous_n = per_day[1][1] if len(per_day) > 1 else None
    status = dict(
        _rows(
            conn,
            "WITH l AS (SELECT DISTINCT ON (source, dataset, partition)"
            " CASE WHEN status='noop' THEN 'loaded' ELSE status END AS status FROM partition_load"
            " ORDER BY source, dataset, partition, id DESC)"
            " SELECT status, count(*) FROM l GROUP BY 1",
        )
    )
    quarantined = [
        _iso(r[0])
        for r in _rows(
            conn,
            "WITH l AS (SELECT DISTINCT ON (source, dataset, partition) partition, status"
            " FROM partition_load ORDER BY source, dataset, partition, id DESC)"
            " SELECT partition FROM l WHERE status='quarantined' ORDER BY 1",
        )
    ]
    instruments = dict(_rows(conn, "SELECT status, count(*) FROM instrument GROUP BY 1"))
    return {
        "bars": bars, "instruments_with_bars": with_bars,
        "first_date": None if first is None else first.astimezone(IST).date().isoformat(),
        "last_date": None if last is None else last.astimezone(IST).date().isoformat(),
        "bars_on_last_date": latest_n, "bars_on_previous_date": previous_n,
        "partitions": status, "quarantined_partitions": quarantined, "instruments": instruments,
    }  # fmt: skip


def corporate_action_health(conn: psycopg.Connection) -> dict[str, Any]:
    by_status = dict(_rows(conn, "SELECT status, count(*) FROM corporate_action GROUP BY 1"))
    resolutions = dict(_rows(conn, "SELECT status, count(*) FROM action_resolution GROUP BY 1"))
    return {"actions_by_status": by_status, "resolutions_by_status": resolutions}


def research_health(conn: psycopg.Connection) -> dict[str, Any]:
    runs = _one(conn, "SELECT count(*) FROM backtest_run")[0]
    latest = _rows(
        conn,
        "SELECT run_id, strategy_id, created_at, accounting_complete, ledger_reconciled"
        " FROM backtest_run ORDER BY run_id DESC LIMIT 1",
    )
    vr = _one(conn, "SELECT count(*), count(*) FILTER (WHERE passed) FROM validation_report")
    exp = _one(conn, "SELECT count(*) FROM experiment")[0]
    return {
        "backtests": runs, "experiments": exp,
        "validation_reports": vr[0], "validation_reports_passed": vr[1],
        "latest_run": None if not latest else {
            "run_id": latest[0][0], "strategy_id": latest[0][1], "created_at": _iso(latest[0][2]),
            "accounting_complete": latest[0][3], "ledger_reconciled": latest[0][4]},
    }  # fmt: skip


def ingestion_activity(
    conn: psycopg.Connection, limit: int = 25, offset: int = 0
) -> dict[str, Any]:
    """Load events newest first. A row is `superseded` when a later load of the same partition
    exists, and carries that partition's CURRENT status, so an old quarantine that was resolved
    never reads as a live problem."""
    total = _one(conn, "SELECT count(*) FROM partition_load")[0]
    rows = _rows(
        conn,
        "SELECT p.id, p.source, p.dataset, p.partition, p.status, p.at, c.status, c.id"
        " FROM partition_load p JOIN LATERAL (SELECT status, id FROM partition_load q"
        " WHERE q.source=p.source AND q.dataset=p.dataset AND q.partition=p.partition"
        " ORDER BY q.id DESC LIMIT 1) c ON true ORDER BY p.id DESC LIMIT %s OFFSET %s",
        (limit, offset),
    )
    items = [
        {"id": r[0], "source": r[1], "dataset": r[2], "partition": _iso(r[3]), "status": r[4],
         "at": _iso(r[5]), "current_status": r[6], "superseded": r[7] != r[0]} for r in rows
    ]  # fmt: skip
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def search_instruments(conn: psycopg.Connection, q: str, limit: int = 20) -> list[dict[str, Any]]:
    term = q.strip().upper().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like = f"{term}%"
    rows = _rows(
        conn,
        "SELECT instrument_id, symbol, isin, name, status, listed_on, delisted_on FROM instrument"
        " WHERE upper(symbol) LIKE %s OR upper(coalesce(isin,'')) LIKE %s"
        " OR upper(coalesce(name,'')) LIKE %s ORDER BY (upper(symbol)=%s) DESC, symbol LIMIT %s",
        (like, like, f"%{term}%", q.strip().upper(), limit),
    )
    return [_instrument(r) for r in rows]


def _instrument(r: tuple[Any, ...]) -> dict[str, Any]:
    return {"id": r[0], "symbol": r[1], "isin": r[2], "name": r[3], "status": r[4],
            "listed_on": _iso(r[5]), "delisted_on": _iso(r[6])}  # fmt: skip


def instrument(conn: psycopg.Connection, instrument_id: int) -> dict[str, Any] | None:
    rows = _rows(
        conn,
        "SELECT instrument_id, symbol, isin, name, status, listed_on, delisted_on FROM instrument"
        " WHERE instrument_id=%s",
        (instrument_id,),
    )
    if not rows:
        return None
    first, last, n = _one(
        conn,
        f"SELECT min({IST_DAY}), max({IST_DAY}), count(*) FROM bar_1d WHERE instrument_id=%s",
        (instrument_id,),
    )
    out = _instrument(rows[0])
    out["bars"] = {"first": _iso(first), "last": _iso(last), "count": n}
    return out


def instrument_actions(conn: psycopg.Connection, instrument_id: int) -> list[dict[str, Any]]:
    rows = _rows(
        conn,
        "SELECT ex_date, kind, status, num, den, amount, subject FROM corporate_action"
        " WHERE instrument_id=%s ORDER BY ex_date, id",
        (instrument_id,),
    )
    return [
        {"ex_date": _iso(r[0]), "kind": r[1], "status": r[2], "num": _s(r[3]), "den": _s(r[4]),
         "amount": _s(r[5]), "subject": r[6]} for r in rows
    ]  # fmt: skip


def _s(v: Any) -> str | None:
    return None if v is None else str(v)


def instrument_bars(
    conn: psycopg.Connection, instrument_id: int, start: date, end: date, adjust: str
) -> dict[str, Any]:
    h = BarReader(conn).history(instrument_id, start, end, adjust=adjust)
    return {
        "adjust": adjust,
        "adjustment_version": h.adjustment_version,
        "clean": h.clean,
        "bars": [
            {"date": b.ts.astimezone(IST).date().isoformat(), "open": str(b.open),
             "high": str(b.high), "low": str(b.low), "close": str(b.close), "volume": str(b.volume),
             "factor": str(b.factor)} for b in h.bars
        ],
        "unapplied": [{"kind": a.kind, "ex_date": a.ex_date.isoformat()} for a in h.unapplied],
        "provisional": [{"kind": a.kind, "ex_date": a.ex_date.isoformat()} for a in h.provisional],
    }  # fmt: skip


def benchmarks(conn: psycopg.Connection) -> list[dict[str, Any]]:
    out = []
    for bid, name, symbol, rtype, method in _rows(
        conn,
        "SELECT benchmark_id, name, index_symbol, return_type, methodology_version FROM benchmark"
        " ORDER BY benchmark_id",
    ):
        first, last, n = _one(
            conn,
            "SELECT min(observation_date), max(observation_date), count(*)"
            " FROM benchmark_observation WHERE benchmark_id=%s",
            (bid,),
        )
        out.append({
            "id": bid, "name": name, "index_symbol": symbol, "return_type": rtype,
            "methodology_version": method, "first": _iso(first), "last": _iso(last),
            "observations": n, "dataset_hash": dataset_hash(conn, bid),
        })  # fmt: skip
    return out


def benchmark_validations(conn: psycopg.Connection, benchmark_id: int) -> list[dict[str, Any]]:
    rows = _rows(
        conn,
        "SELECT validation_id, created_at, passed, dataset_hash, report, unresolved"
        " FROM benchmark_validation WHERE benchmark_id=%s ORDER BY validation_id DESC",
        (benchmark_id,),
    )
    current = dataset_hash(conn, benchmark_id)
    return [
        {"validation_id": r[0], "created_at": _iso(r[1]), "passed": r[2],
         "covers_current_dataset": r[3] == current,
         "report_version": r[4].get("report_version", "legacy"),
         "technical_validation_passed": r[4].get("technical_validation_passed", r[2]),
         "check_states": r[4].get("check_states"),
         "owner_accepted_findings": r[4].get("owner_accepted_findings", []),
         "unresolved": r[5]} for r in rows
    ]  # fmt: skip


def benchmark_levels(
    conn: psycopg.Connection,
    benchmark_id: int,
    start: date | None,
    end: date | None,
    max_points: int,
) -> list[dict[str, str]]:
    lv = sorted(levels(conn, benchmark_id, start, end).items())
    step = max(1, -(-len(lv) // max_points))
    keep = lv[::step]
    if lv and keep[-1] != lv[-1]:
        keep.append(lv[-1])
    return [{"date": d.isoformat(), "level": str(v)} for d, v in keep]


def backtests(conn: psycopg.Connection, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    total = _one(conn, "SELECT count(*) FROM backtest_run")[0]
    rows = _rows(
        conn,
        "SELECT run_id, strategy_id, strategy_version, reader_mode, created_at, metrics,"
        " accounting_complete, ledger_reconciled, result_hash FROM backtest_run"
        " ORDER BY run_id DESC LIMIT %s OFFSET %s",
        (limit, offset),
    )
    items = [
        {"run_id": r[0], "strategy_id": r[1], "strategy_version": r[2], "reader_mode": r[3],
         "created_at": _iso(r[4]), "metrics": r[5], "accounting_complete": r[6],
         "ledger_reconciled": r[7], "result_hash": r[8]} for r in rows
    ]  # fmt: skip
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def backtest(conn: psycopg.Connection, run_id: int) -> dict[str, Any] | None:
    rows = _rows(
        conn,
        "SELECT run_id, strategy_id, strategy_version, params, params_hash, code_version,"
        " reader_mode, config, cost_model, adjustment_versions, provisional_events,"
        " unapplied_events, blocked_instruments, unmodelled_events, accounting_complete,"
        " dividends_received, metrics,"
        " result_hash, created_at, ledger_reconciled, reconciliation, pnl FROM backtest_run"
        " WHERE run_id=%s",
        (run_id,),
    )
    if not rows:
        return None
    keys = ["run_id", "strategy_id", "strategy_version", "params", "params_hash", "code_version",
            "reader_mode", "config", "cost_model", "adjustment_versions", "provisional_events",
            "unapplied_events", "blocked_instruments", "unmodelled_events", "accounting_complete",
            "dividends_received", "metrics", "result_hash", "created_at", "ledger_reconciled",
            "reconciliation", "pnl"]  # fmt: skip
    return {
        k: (_s(v) if k == "dividends_received" else _iso(v))
        for k, v in zip(keys, rows[0], strict=True)
    }
