"""Read-only SQL behind the API. Every value is returned as the database holds it: prices and
levels as strings (never floats), dates as ISO strings. Nothing is calculated here that a backend
service already owns (adjustment, eligibility, metrics)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import psycopg

from algo.data.bars import Bar
from algo.data.benchmark import dataset_hash, levels
from algo.data.minute_reader import minute_history
from algo.data.reader import IST, BarReader
from algo.data.resample import resample
from algo.indicators.catalog import CATALOG, Bars, Indicator, compute

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
    unresolved = _one(
        conn,
        "SELECT count(*) FROM corporate_action c WHERE c.status='review' AND NOT EXISTS"
        " (SELECT 1 FROM action_resolution r WHERE r.instrument_id=c.instrument_id"
        " AND r.ex_date=c.ex_date AND r.kind=c.kind)",
    )[0]
    return {
        "actions_by_status": by_status,
        "resolutions_by_status": resolutions,
        "total_events": sum(by_status.values()),
        "verified": by_status.get("ok", 0),
        "pending_review": by_status.get("review", 0),
        "review_without_any_resolution": unresolved,
        "provisional_adjustments": resolutions.get("provisional", 0),
        "no_adjustment_verified": resolutions.get("no_adjustment_verified", 0),
        "ignored_with_reason": resolutions.get("ignored_with_reason", 0),
    }


def known_holidays(conn: psycopg.Connection) -> frozenset[date]:
    """Days the exchange published no daily file (the platform's only evidence of a holiday)."""
    rows = _rows(
        conn,
        "WITH l AS (SELECT DISTINCT ON (source, dataset, partition) partition, status FROM"
        " partition_load ORDER BY source, dataset, partition, id DESC)"
        " SELECT partition FROM l WHERE status='not_published'",
    )
    return frozenset(r[0] for r in rows)


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


def _ist_day(ts: datetime) -> date:
    return ts.astimezone(IST).date()


INTRADAY_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}


def instrument_intraday_bars(
    conn: psycopg.Connection,
    instrument_id: int,
    start: date,
    end: date,
    adjust: str,
    timeframe: str,
) -> dict[str, Any]:
    # Built at read time from the stored 1-minute bars (the only intraday copy), one instrument's
    # own (no ISIN-change stitching). `time` = UTC epoch seconds of the bar open.
    h = minute_history(conn, instrument_id, start, end, adjust=adjust)
    factor_of_day = {b.ts.astimezone(IST).date(): b.factor for b in h.bars}
    minutes = [
        Bar(str(instrument_id), b.ts, b.open, b.high, b.low, b.close, b.volume) for b in h.bars
    ]
    out = resample(minutes, INTRADAY_MINUTES[timeframe])
    return {
        "adjust": adjust,
        "timeframe": timeframe,
        "adjustment_version": h.adjustment_version,
        "clean": h.clean,
        "bars": [
            {"time": int(b.ts.astimezone(UTC).timestamp()), "date": _ist_day(b.ts).isoformat(),
             "open": str(b.open), "high": str(b.high), "low": str(b.low), "close": str(b.close),
             "volume": str(b.volume), "factor": str(factor_of_day[_ist_day(b.ts)]),
             "instrument_id": instrument_id} for b in out
        ],
        "unapplied": [{"kind": a.kind, "ex_date": a.ex_date.isoformat()} for a in h.unapplied],
        "provisional": [{"kind": a.kind, "ex_date": a.ex_date.isoformat()} for a in h.provisional],
    }  # fmt: skip


def instrument_bars(
    conn: psycopg.Connection, instrument_id: int, start: date, end: date, adjust: str
) -> dict[str, Any]:
    # Issuer-scoped: one continuous history across an ISIN change; each bar names the instrument
    # that traded it (`instrument_id`), so the transition is visible and nothing is merged.
    h = BarReader.for_env(conn).issuer_history(instrument_id, start, end, adjust=adjust)
    return {
        "adjust": adjust,
        "timeframe": "1d",
        "adjustment_version": h.adjustment_version,
        "clean": h.clean,
        "bars": [
            {"date": b.ts.astimezone(IST).date().isoformat(), "open": str(b.open),
             "high": str(b.high), "low": str(b.low), "close": str(b.close), "volume": str(b.volume),
             "factor": str(b.factor), "instrument_id": b.owner} for b in h.bars
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
) -> dict[str, Any]:
    """The stored observations in [start, end]. If they fit in max_points all are returned. If not,
    each bucket of consecutive observations keeps its lowest and highest level (so no peak or trough
    disappears), plus the first and last observation; the reply says it was down-sampled."""
    lv = sorted(levels(conn, benchmark_id, start, end).items())
    total = len(lv)
    if total <= max_points:
        keep = lv
    else:
        size = -(-total * 2 // max_points)  # observations per bucket: two kept from each
        picked = {0, total - 1}
        for lo in range(0, total, size):
            bucket = range(lo, min(lo + size, total))
            picked.add(min(bucket, key=lambda i: lv[i][1]))
            picked.add(max(bucket, key=lambda i: lv[i][1]))
        keep = [lv[i] for i in sorted(picked)]
    return {
        "levels": [{"date": d.isoformat(), "level": str(v)} for d, v in keep],
        "total_observations": total,
        "returned": len(keep),
        "downsampled": len(keep) < total,
        "method": "min-max per bucket (extremes preserved)"
        if len(keep) < total
        else "all observations",
    }


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


_Q = Decimal("0.0001")


def _text(v: Decimal | None) -> str | None:
    return None if v is None else format(v.quantize(_Q), "f")


def _num(v: Decimal) -> str:
    return format(v.normalize(), "f")


def indicator_catalog() -> list[dict[str, Any]]:
    return [
        {
            "name": i.name, "label": i.label, "group": i.group, "pane": i.pane,
            "description": i.description,
            "params": [
                {"key": p.key, "label": p.label, "default": _num(p.default), "min": _num(p.lo),
                 "max": _num(p.hi), "integer": p.integer}
                for p in i.params
            ],
            "outputs": [
                {"key": o.key, "label": o.label, "kind": o.kind, "color": o.color}
                for o in i.outputs
            ],
            "levels": [_num(v) for v in i.levels],
        }
        for i in CATALOG.values()
    ]  # fmt: skip


def indicator_series(
    conn: psycopg.Connection, instrument_id: int, start: date, end: date, adjust: str,
    specs: list[str],
) -> dict[str, Any]:  # fmt: skip
    """Indicators over the instrument's WHOLE history up to `end` (so the first visible value is
    already warmed up), returned for [start, end] only. Computed by algo.indicators on the same
    adjusted bars the chart draws, as strings; None where an indicator has no value yet."""
    h = BarReader.for_env(conn).issuer_history(instrument_id, date(1900, 1, 1), end, adjust=adjust)
    bars = Bars(
        [b.open for b in h.bars], [b.high for b in h.bars], [b.low for b in h.bars],
        [b.close for b in h.bars], [b.volume for b in h.bars],
    )  # fmt: skip
    days = [b.ts.astimezone(IST).date() for b in h.bars]
    keep = [i for i, d in enumerate(days) if start <= d <= end]
    out = []
    for spec in specs:
        ind, params, series = compute(spec, bars)
        out.append(
            _indicator_json(ind, params, [{k: [v[i] for i in keep] for k, v in series.items()}][0])
        )
    return {
        "adjust": adjust, "adjustment_version": h.adjustment_version,
        "dates": [days[i].isoformat() for i in keep], "indicators": out,
    }  # fmt: skip


def _indicator_json(
    ind: Indicator, params: dict[str, Decimal], series: dict[str, Any]
) -> dict[str, Any]:
    shown = [_num(params[p.key]) for p in ind.params]
    return {
        "spec": ":".join([ind.name, *shown]), "name": ind.name,
        "label": " ".join([ind.name.upper() if ind.name != "bb" else "BB", *shown]),
        "pane": ind.pane, "params": {k: _num(v) for k, v in params.items()},
        "levels": [_num(v) for v in ind.levels],
        "outputs": [{"key": o.key, "label": o.label, "kind": o.kind, "color": o.color,
                     "values": [_text(v) for v in series[o.key]]} for o in ind.outputs],
    }  # fmt: skip
