# ruff: noqa: E501
"""S1 bar-storage benchmark (docs/benchmarks/S1-bars-storage.md). Works in a throwaway schema, drops it, touches no platform table.
usage: bench_bars.py [--db URL] [--rows 5000000] [--instruments 500] [--keep]
Exit 1 when any criterion fails."""

import argparse
import io
import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta

import psycopg

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--rows", type=int, default=5_000_000)
ap.add_argument("--instruments", type=int, default=500)
ap.add_argument(
    "--timescale",
    action="store_true",
    help="hypertable + compression + continuous aggregate (needs the TimescaleDB extension)",
)
ap.add_argument("--keep", action="store_true", help="leave the schema for inspection")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
SESSION = 375
SCHEMA = f"bench_bars_{os.getpid()}"
CRITERIA = {
    "ingest_rows_per_s": (">=", 50_000),
    "one_instrument_year_ms": ("<=", 250),
    "session_500_ms": ("<=", 1500),
    "daily_rollup_ms": ("<=", 500),
}
if a.timescale:  # criteria 6-8 of docs/benchmarks/S1-bars-storage.md
    CRITERIA |= {
        "compression_ratio": (">=", 4),
        "cagg_refresh_s_per_million_rows": ("<=", 5),
        "compressed_one_instrument_year_ms": ("<=", 250),
        "compressed_session_500_ms": ("<=", 1500),
        "compressed_daily_rollup_ms": ("<=", 500),
    }
results: dict[str, float] = {}


def say(name: str, value: float, unit: str) -> None:
    print(
        json.dumps({"measure": name, "value": round(value, 2), "unit": unit, "rows": a.rows}),
        flush=True,
    )


def timed(conn: psycopg.Connection, sql: str, args: tuple[object, ...] = ()) -> float:
    t = time.perf_counter()
    conn.execute(sql, args).fetchall()
    return (time.perf_counter() - t) * 1000


per_instrument = max(a.rows // a.instruments, SESSION)
sessions = -(-per_instrument // SESSION)
start = datetime(2025, 1, 1, 3, 45, tzinfo=UTC)
with psycopg.connect(a.db, autocommit=True) as conn:
    conn.execute(f"CREATE SCHEMA {SCHEMA}")
    try:
        conn.execute(f"SET search_path = {SCHEMA}, public")  # public: the TimescaleDB functions
        conn.execute(
            "CREATE TABLE bar (instrument_id BIGINT NOT NULL, ts TIMESTAMPTZ NOT NULL, open NUMERIC NOT NULL, high NUMERIC NOT NULL, low NUMERIC NOT NULL, close NUMERIC NOT NULL, volume BIGINT NOT NULL, PRIMARY KEY (instrument_id, ts))"
        )
        if a.timescale:
            conn.execute(
                "SELECT create_hypertable('bar', 'ts', chunk_time_interval => INTERVAL '90 days')"
            )
        total, copy_s = 0, 0.0
        for iid in range(1, a.instruments + 1):
            buf = io.StringIO()
            day, left = start, per_instrument
            for _ in range(sessions):
                if day.weekday() >= 5:
                    day += timedelta(days=2 if day.weekday() == 5 else 1)
                n = min(SESSION, left)
                for m in range(n):
                    p = 100 + (iid % 50) + ((m * 7) % 13) / 10
                    buf.write(
                        f"{iid}\t{(day + timedelta(minutes=m)).isoformat()}\t{p}\t{p + 0.2}\t{p - 0.2}\t{p + 0.1}\t{1000 + m}\n"
                    )
                left -= n
                day += timedelta(days=1)
                if left <= 0:
                    break
            data = buf.getvalue()
            t0 = time.perf_counter()
            with conn.cursor().copy("COPY bar FROM STDIN") as cp:
                cp.write(data)
            copy_s += time.perf_counter() - t0  # only the database's time, not the generator's
            total += data.count("\n")
        conn.execute("ANALYZE bar")
        rate = total / copy_s
        results["ingest_rows_per_s"] = rate
        say("ingest", rate, "rows/s")
        size = conn.execute(
            "SELECT hypertable_size('bar')"
            if a.timescale
            else "SELECT pg_total_relation_size('bar')"
        ).fetchone()[0]  # type: ignore[index]
        say("size_per_million_rows", size / (total / 1e6) / 1e6, "MB")
        last = conn.execute("SELECT max(ts) FROM bar WHERE instrument_id=1").fetchone()[0]  # type: ignore[index]
        lo = last - timedelta(days=365)
        results["one_instrument_year_ms"] = min(
            timed(
                conn, "SELECT * FROM bar WHERE instrument_id=1 AND ts BETWEEN %s AND %s", (lo, last)
            )
            for _ in range(3)
        )
        say("one_instrument_year", results["one_instrument_year_ms"], "ms")
        day0 = conn.execute("SELECT min(ts) FROM bar WHERE instrument_id=1").fetchone()[0]  # type: ignore[index]
        results["session_500_ms"] = min(
            timed(
                conn,
                "SELECT * FROM bar WHERE ts >= %s AND ts < %s",
                (day0, day0 + timedelta(hours=7)),
            )
            for _ in range(3)
        )
        say("session_500_instruments", results["session_500_ms"], "ms")
        results["daily_rollup_ms"] = min(
            timed(
                conn,
                "SELECT date_trunc('day', ts), min(low), max(high), sum(volume) FROM bar WHERE instrument_id=1 GROUP BY 1",
            )
            for _ in range(3)
        )
        say("daily_rollup_one_instrument", results["daily_rollup_ms"], "ms")
        if a.timescale:
            before = conn.execute("SELECT hypertable_size('bar')").fetchone()[0]  # type: ignore[index]
            conn.execute(
                "CREATE MATERIALIZED VIEW daily WITH (timescaledb.continuous) AS SELECT instrument_id, time_bucket('1 day', ts) AS d, min(low) AS low, max(high) AS high, sum(volume) AS volume FROM bar GROUP BY 1, 2 WITH NO DATA"
            )
            t = time.perf_counter()
            conn.execute("CALL refresh_continuous_aggregate('daily', NULL, NULL)")
            results["cagg_refresh_s_per_million_rows"] = (time.perf_counter() - t) / (total / 1e6)
            say("cagg_refresh", results["cagg_refresh_s_per_million_rows"], "s per million rows")
            conn.execute(
                "ALTER TABLE bar SET (timescaledb.compress, timescaledb.compress_segmentby = 'instrument_id', timescaledb.compress_orderby = 'ts')"
            )
            conn.execute("SELECT compress_chunk(c) FROM show_chunks('bar') c")
            after = conn.execute("SELECT hypertable_size('bar')").fetchone()[0]  # type: ignore[index]
            results["compression_ratio"] = before / after
            say("compression_ratio", results["compression_ratio"], "x")
            results["compressed_one_instrument_year_ms"] = min(
                timed(
                    conn,
                    "SELECT * FROM bar WHERE instrument_id=1 AND ts BETWEEN %s AND %s",
                    (lo, last),
                )
                for _ in range(3)
            )
            results["compressed_session_500_ms"] = min(
                timed(
                    conn,
                    "SELECT * FROM bar WHERE ts >= %s AND ts < %s",
                    (day0, day0 + timedelta(hours=7)),
                )
                for _ in range(3)
            )
            results["compressed_daily_rollup_ms"] = min(
                timed(
                    conn,
                    "SELECT date_trunc('day', ts), min(low), max(high), sum(volume) FROM bar WHERE instrument_id=1 GROUP BY 1",
                )
                for _ in range(3)
            )
            for k in (
                "compressed_one_instrument_year_ms",
                "compressed_session_500_ms",
                "compressed_daily_rollup_ms",
            ):
                say(k, results[k], "ms")
    finally:
        if not a.keep:
            conn.execute("SET search_path = public")
            conn.execute(f"DROP SCHEMA {SCHEMA} CASCADE")
bad = [
    k
    for k, (op, limit) in CRITERIA.items()
    if not (results[k] >= limit if op == ">=" else results[k] <= limit)
]
for k, (op, limit) in CRITERIA.items():
    print(f"{'FAIL' if k in bad else 'PASS'} {k}: {results[k]:.1f} (needs {op} {limit})")
sys.exit(1 if bad else 0)
