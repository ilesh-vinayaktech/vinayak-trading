"""Read-only SQL behind the API. Every value is returned as the database holds it: prices and
levels as strings (never floats), dates as ISO strings. Nothing is calculated here that a backend
service already owns (adjustment, eligibility, metrics)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import psycopg

from algo.backtest.report import build_report, no_comparison
from algo.backtest.store import run_splits
from algo.data import ratios as fr
from algo.data.bars import Bar
from algo.data.benchmark import DEFAULT_BENCHMARK, dataset_hash, levels, validated
from algo.data.fundamentals import load_market, load_quarters
from algo.data.minute_reader import minute_history
from algo.data.reader import IST, AdjBar, BarReader
from algo.data.resample import resample, resample_calendar
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
    """One row per partition: its latest load event, newest first. Earlier events for the same
    date (a "no file yet" before the file came out, a quarantine that was later fixed) stay in the
    log but are not listed, so nothing stale reads as a current problem."""
    latest = (
        "WITH latest AS (SELECT DISTINCT ON (source, dataset, partition)"
        " id, source, dataset, partition, status, at FROM partition_load"
        " ORDER BY source, dataset, partition, id DESC)"
    )
    total = _one(conn, f"{latest} SELECT count(*) FROM latest")[0]
    rows = _rows(
        conn,
        f"{latest} SELECT id, source, dataset, partition, status, at FROM latest"
        " ORDER BY id DESC LIMIT %s OFFSET %s",
        (limit, offset),
    )
    items = [
        {"id": r[0], "source": r[1], "dataset": r[2], "partition": _iso(r[3]), "status": r[4],
         "at": _iso(r[5])} for r in rows
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
        f"SELECT min({IST_DAY}), max({IST_DAY}), count(DISTINCT ts) FROM bar_1d"
        " WHERE instrument_id=%s",
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


def instrument_upcoming(conn: psycopg.Connection, instrument_id: int) -> list[dict[str, Any]]:
    """Actions NSE has announced whose ex-date has not come yet, soonest first. For information:
    they are not part of the history and no price is adjusted for them."""
    rows = _rows(
        conn,
        "SELECT ex_date, kind, status, num, den, amount, subject FROM corporate_action_upcoming"
        " WHERE instrument_id=%s ORDER BY ex_date, kind",
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


INTRADAY_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "10m": 10, "15m": 15, "30m": 30, "45m": 45,
                    "1h": 60, "2h": 120, "3h": 180, "4h": 240}  # fmt: skip


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
    # Days the stored history does not have yet (today, until Kite's minutes are loaded) come from
    # the live feed's finished minutes: as traded, and nothing after them can need an adjustment.
    live = conn.execute(
        "SELECT ts, open, high, low, close, volume FROM live_bar_1m"
        " WHERE instrument_id=%s AND ts >= %s AND ts < %s ORDER BY ts",
        (
            instrument_id,
            datetime.combine(start, time(0), IST),
            datetime.combine(end + timedelta(days=1), time(0), IST),
        ),
    ).fetchall()
    for r in live:
        if _ist_day(r[0]) not in factor_of_day:
            minutes.append(Bar(str(instrument_id), *r))
    for r in live:
        factor_of_day.setdefault(_ist_day(r[0]), Decimal(1))
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


def reader_for(conn: psycopg.Connection, instrument_id: int) -> tuple[BarReader, str]:
    """The reader for one stock's daily bars, and the source it reads ("kite" or "nse").

    With ALGO_PRICE_SOURCE=kite a stock reads Kite's candles. Kite is mapped to a few hundred
    names and bhavcopy covers thousands, so a stock with no Kite candles reads bhavcopy and the
    caller says so. Only the explorer views (chart, indicators, signals) do this; the paper
    runner and backtests keep their own strict choice.
    """
    reader = BarReader.for_env(conn)
    if reader.source == "kite" and (
        conn.execute(
            "SELECT 1 FROM bar_1d WHERE instrument_id=%s AND source='kite' LIMIT 1",
            (instrument_id,),
        ).fetchone()
        is None
    ):
        return BarReader(conn), "nse"
    return reader, reader.source


CALENDAR_PERIODS = {"1w": "week", "1mo": "month"}


def instrument_bars(
    conn: psycopg.Connection,
    instrument_id: int,
    start: date,
    end: date,
    adjust: str,
    timeframe: str = "1d",
) -> dict[str, Any]:
    # Issuer-scoped: one continuous history across an ISIN change; each bar names the instrument
    # that traded it (`instrument_id`), so the transition is visible and nothing is merged.
    # 1w / 1mo are rolled up from these adjusted daily bars (dated by their first trading day).
    reader, source = reader_for(conn, instrument_id)
    h = reader.issuer_history(instrument_id, start, end, adjust=adjust)
    if timeframe in CALENDAR_PERIODS:
        by_ts = {b.ts: b for b in h.bars}
        rolled = resample_calendar(
            [Bar(str(b.owner), b.ts, b.open, b.high, b.low, b.close, b.volume) for b in h.bars],
            CALENDAR_PERIODS[timeframe],
        )
        h.bars = [
            AdjBar(
                r.ts,
                r.open,
                r.high,
                r.low,
                r.close,
                r.volume,
                by_ts[r.ts].factor,
                by_ts[r.ts].owner,
            )
            for r in rolled
        ]
    return {
        "adjust": adjust,
        "timeframe": timeframe,
        "source": source,
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
        "SELECT r.run_id, r.strategy_id, r.strategy_version, r.reader_mode, r.created_at,"
        " r.metrics, r.accounting_complete, r.ledger_reconciled, r.result_hash, r.label,"
        " s.experiment_id, s.name"
        " FROM backtest_run r LEFT JOIN LATERAL ("
        " SELECT e.experiment_id, e.name FROM study_trial t"
        " JOIN experiment e USING (experiment_id)"
        " WHERE t.backtest_run = r.run_id LIMIT 1) s ON true"
        " ORDER BY r.run_id DESC LIMIT %s OFFSET %s",
        (limit, offset),
    )
    items = [
        {"run_id": r[0], "strategy_id": r[1], "strategy_version": r[2], "reader_mode": r[3],
         "created_at": _iso(r[4]), "metrics": r[5], "accounting_complete": r[6],
         "ledger_reconciled": r[7], "result_hash": r[8], "label": r[9],
         "study": None if r[10] is None else {"experiment_id": r[10], "name": r[11]}} for r in rows
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


def backtest_report(conn: psycopg.Connection, run_id: int) -> dict[str, Any] | None:
    """The run explained: buys paired with sells, the equity curve, results per stock."""
    run = _rows(
        conn,
        "SELECT strategy_id, strategy_version, params, config, created_at, label, pnl,"
        " dividends_received FROM backtest_run WHERE run_id=%s",
        (run_id,),
    )
    if not run:
        return None
    fills = [
        (r[0], r[1], r[2], r[3], r[4], r[5], r[6])
        for r in _rows(
            conn,
            "SELECT seq, day, instrument_id, side, qty, price, cost"
            " FROM backtest_trade WHERE run_id=%s",
            (run_id,),
        )
    ]
    equity = [
        (r[0], r[1])
        for r in _rows(
            conn, "SELECT day, equity FROM backtest_equity WHERE run_id=%s ORDER BY day", (run_id,)
        )
    ]
    names = {
        r[0]: r[1]
        for r in _rows(
            conn,
            "SELECT instrument_id, symbol FROM instrument WHERE instrument_id = ANY(%s)",
            (sorted({f[2] for f in fills}),),
        )
    }
    sid, ver, params, cfg, created, label, pnl, dividends = run[0]
    bench: tuple[str, Any] | None = None
    row = conn.execute(
        "SELECT benchmark_id FROM benchmark WHERE name=%s", (DEFAULT_BENCHMARK,)
    ).fetchone()
    if row is not None and validated(conn, row[0]) and equity:
        bench = (DEFAULT_BENCHMARK, levels(conn, row[0], equity[0][0], equity[-1][0]))
    report = build_report(
        fills,
        equity,
        Decimal(str(cfg["initial_cash"])),
        names,
        bench,
        run_splits(conn, run_id),
        total_charges=Decimal(pnl["fees"]) if "fees" in pnl else None,
        dividends=Decimal(dividends),
    )
    if bench is None:
        why = "is not loaded" if row is None else "has no passing validation for its stored data"
        report["benchmark"] = no_comparison(DEFAULT_BENCHMARK, f"{DEFAULT_BENCHMARK} {why}")
    study = conn.execute(
        "SELECT e.experiment_id, e.name FROM study_trial t JOIN experiment e USING (experiment_id)"
        " WHERE t.backtest_run=%s LIMIT 1",
        (run_id,),
    ).fetchone()
    return {
        "study": None if study is None else {"experiment_id": study[0], "name": study[1]},
        "label": label,
        "run_id": run_id, "strategy_id": sid, "strategy_version": ver, "params": params,
        "start": cfg.get("start"), "end": cfg.get("end"), "created_at": _iso(created), **report,
    }  # fmt: skip


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
    specs: list[str], timeframe: str = "1d",
) -> dict[str, Any]:  # fmt: skip
    """Indicators on the SAME bars the chart draws for `timeframe`, returned for [start, end].
    1d, 1w and 1mo use the whole stored history up to `end`, so the first value is warmed up;
    intraday uses only [start, end] (the window those minutes are served for) and adds `times`
    (UTC epoch seconds) beside `dates`. Strings; None where there is no value yet."""
    if timeframe in INTRADAY_MINUTES:
        rows = instrument_intraday_bars(conn, instrument_id, start, end, adjust, timeframe)
    else:
        rows = instrument_bars(conn, instrument_id, date(1900, 1, 1), end, adjust, timeframe)
    bars = Bars(
        *([Decimal(r[k]) for r in rows["bars"]] for k in ("open", "high", "low", "close", "volume"))
    )
    days = [date.fromisoformat(r["date"]) for r in rows["bars"]]
    keep = [i for i, d in enumerate(days) if start <= d <= end]
    out = []
    for spec in specs:
        ind, params, series = compute(spec, bars)
        out.append(
            _indicator_json(ind, params, {k: [v[i] for i in keep] for k, v in series.items()})
        )
    res: dict[str, Any] = {
        "adjust": adjust, "adjustment_version": rows["adjustment_version"],
        "dates": [days[i].isoformat() for i in keep], "indicators": out,
    }  # fmt: skip
    if timeframe in INTRADAY_MINUTES:
        res["times"] = [rows["bars"][i]["time"] for i in keep]
    return res


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


def instrument_fundamentals(
    conn: psycopg.Connection, instrument_id: int, basis: str | None, quarters: int
) -> dict[str, Any] | None:
    """Latest filing per quarter (a restatement replaces the earlier), every figure it carries."""
    inst = conn.execute(
        "SELECT symbol FROM instrument WHERE instrument_id=%s", (instrument_id,)
    ).fetchone()
    if inst is None:
        return None
    bases = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT basis FROM fundamental_filing WHERE instrument_id=%s ORDER BY basis",
            (instrument_id,),
        )
    ]
    first = "CONSOLIDATED" if "CONSOLIDATED" in bases else (bases[0] if bases else None)
    chosen = basis if basis in bases else first
    periods: list[dict[str, Any]] = []
    if chosen is not None:
        filings = conn.execute(
            "SELECT * FROM (SELECT DISTINCT ON (period_end) filing_id, period_start, period_end,"
            " filed_at, audited, bank, rounding FROM fundamental_filing"
            " WHERE instrument_id=%s AND basis=%s ORDER BY period_end, filed_at DESC) f"
            " ORDER BY period_end DESC LIMIT %s",
            (instrument_id, chosen, quarters),
        ).fetchall()
        scopes = ("QUARTER", "YTD", "INSTANT")
        facts: dict[int, dict[str, dict[str, str]]] = {
            f[0]: {s: {} for s in scopes} for f in filings
        }
        for fid, scope, metric, value in conn.execute(
            "SELECT filing_id, scope, metric, value FROM fundamental_fact"
            " WHERE filing_id = ANY(%s) AND metric ~ '^[A-Z]'",
            ([f[0] for f in filings],),
        ):
            facts[fid][scope][metric] = str(value)
        periods = [
            {
                "period_start": _iso(f[1]), "period_end": _iso(f[2]), "filed_at": f[3].isoformat(),
                "audited": f[4], "bank": f[5], "rounding": f[6],
                "quarter": facts[f[0]]["QUARTER"], "ytd": facts[f[0]]["YTD"],
                "instant": facts[f[0]]["INSTANT"],
            }
            for f in filings
        ]  # fmt: skip
    return {
        "instrument_id": instrument_id,
        "symbol": inst[0],
        "bases": bases,
        "basis": chosen,
        "periods": periods,
    }


def instrument_ratios(
    conn: psycopg.Connection, instrument_id: int, basis: str | None
) -> dict[str, Any] | None:
    """Ratios now, a year ago and for the last eight quarters, each as filed by then."""
    inst = conn.execute(
        "SELECT symbol FROM instrument WHERE instrument_id=%s", (instrument_id,)
    ).fetchone()
    if inst is None:
        return None
    bases = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT basis FROM fundamental_filing WHERE instrument_id=%s ORDER BY basis",
            (instrument_id,),
        )
    ]
    chosen = basis if basis in bases else ("CONSOLIDATED" if "CONSOLIDATED" in bases else None)
    chosen = chosen or (bases[0] if bases else None)
    out: dict[str, Any] = {
        "instrument_id": instrument_id, "symbol": inst[0], "bases": bases, "basis": chosen,
        "bank": False, "price": None, "latest_period": None, "ratios": [],
    }  # fmt: skip
    if chosen is None:
        return out
    filings = load_quarters(conn, instrument_id, chosen)
    known = fr.known_quarters(filings)
    if not known:
        return out
    market = load_market(conn, instrument_id, max(q.filed_at for q in known[:1]))
    now = fr.compute(known, market)
    # each past quarter as it stood when it was filed: the results known then and the close that day
    history = {
        q.period_end: fr.compute(
            fr.known_quarters(filings, q.filed_at),
            load_market(conn, instrument_id, q.filed_at, q.filed_at.astimezone(IST).date()),
        )
        for q in known[:8]
    }

    def text(v: Decimal | None) -> str | None:
        return None if v is None else str(v.quantize(Decimal("0.0001")))

    ratios = []
    for d in fr.RATIOS:
        if d.key not in now:
            continue
        r, bank = now[d.key], known[0].bank
        rd, basis = fr.reading(d, r.value, bank), "rule"
        if (
            rd is None and d.better is not None
        ):  # no fixed yardstick: judge it against the company's own past quarters
            past = [
                h[d.key].value
                for e, h in history.items()
                if e != known[0].period_end and d.key in h and h[d.key].value is not None
            ]
            rd, basis = (
                fr.reading_vs_own_past(d, r.value, [v for v in past if v is not None]),
                "own_past",
            )
        basis = basis if rd else None
        ago = next(
            (
                history[e].get(d.key)
                for e in history
                if 360 <= (known[0].period_end - e).days <= 370
            ),
            None,
        )
        ratios.append({
            "key": d.key, "label": d.label, "group": d.group, "unit": d.unit, "meaning": d.meaning,
            "formula": d.formula, "better": d.better, "value": text(r.value), "note": r.note,
            "as_of": _iso(r.as_of), "reading": rd, "reading_basis": basis,
            "year_ago": text(ago.value) if ago else None,
            "history": [
                {"period_end": _iso(e), "value": text(h[d.key].value)}
                for e, h in sorted(history.items())
                if d.key in h and h[d.key].value is not None
            ],
        })  # fmt: skip
    out.update(
        bank=known[0].bank, latest_period=_iso(known[0].period_end), ratios=ratios,
        price=None if market.price is None else {"value": text(market.price), "date": _iso(market.price_date)},  # noqa: E501
    )  # fmt: skip
    return out


def _try(conn: psycopg.Connection, fn: Any, default: Any) -> Any:
    """Run a read that needs a table a database may not have yet (a migration not applied),
    inside its own savepoint: a missing table costs the answer, not the request."""
    try:
        with conn.transaction():
            return fn()
    except psycopg.errors.UndefinedTable:
        return default


def scorecard_signals(conn: psycopg.Connection) -> dict[str, Any]:
    """What the three scorecards (algo.api.scorecards) are built from, as stored.
    A signal that has never been recorded is None, not a pass."""
    from algo.data.quality import results

    def newest(check: str) -> str | None:
        got = _try(conn, lambda: results.latest(conn, check), None)
        return None if got is None else str(got[0])

    health = research_health(conn)
    run = health["latest_run"]
    consumed = _try(
        conn,
        lambda: _one(conn, "SELECT EXISTS (SELECT 1 FROM holdout_batch WHERE state='CONSUMED')")[0],
        False,
    )
    return {
        "dq": {k: newest(k) for k in ("completeness", "continuity", "freshness", "kite_reconcile")},
        "latest_run": None
        if run is None
        else {
            "accounting_complete": run["accounting_complete"],
            "ledger_reconciled": run["ledger_reconciled"],
        },
        "validation": {
            "reports": health["validation_reports"],
            "passed": health["validation_reports_passed"],
            "holdout_consumed": bool(consumed),
        },
    }
