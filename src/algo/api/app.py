"""Read-only HTTP API for the research console. Presentation data only: it serves what the backend
already computed (adjusted prices from the bar reader, benchmark eligibility from the frozen audit)
and says plainly what is not persisted yet instead of inventing it. No writes, no live trading."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from algo.api import artifacts, queries

Adjust = Literal["none", "split", "total_return"]


def get_conn(request: Request) -> Iterator[psycopg.Connection]:
    with psycopg.connect(request.app.state.dsn) as c:
        yield c


Conn = Annotated[psycopg.Connection, Depends(get_conn)]


def create_app(
    dsn: str, docs_root: Path, origins: tuple[str, ...] = ("http://localhost:3000",)
) -> FastAPI:
    app = FastAPI(title="Vinayak Trading Research Console API", version="0.1")
    app.state.dsn = dsn
    app.add_middleware(CORSMiddleware, allow_origins=list(origins), allow_methods=["GET"],
                       allow_headers=["*"])  # fmt: skip

    def arts() -> artifacts.Artifacts | None:
        return artifacts.load(docs_root)  # re-read: a new release shows without a restart

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        try:
            with psycopg.connect(dsn, connect_timeout=3) as c:
                c.execute("SELECT 1")
            db = "ok"
        except psycopg.Error as e:
            db = f"error: {type(e).__name__}"
        return {"api": "ok", "database": db, "redis": "not configured"}

    @app.get("/api/dashboard")
    def dashboard(c: Conn) -> dict[str, Any]:
        a = arts()
        bms = queries.benchmarks(c)
        series = []
        for b in bms:
            e = a.eligibility_of(b["id"]) if a else None
            v = queries.benchmark_validations(c, b["id"])
            latest = v[0] if v else None
            series.append({
                "id": b["id"], "name": b["name"], "return_type": b["return_type"],
                "ingested": b["observations"] > 0,
                "technically_validated": bool(latest and latest["technical_validation_passed"]
                                              and latest["covers_current_dataset"]),
                "research_eligible_daily": bool(e and e["uses"]["DAILY_RESEARCH"]["eligible"]),
                "research_eligible_intraday": bool(
                    e and e["uses"]["INTRADAY_RESEARCH"]["eligible"]
                ),
                "benchmark_gate_eligible": bool(e and e["uses"]["BENCHMARK_GATE"]["eligible"]),
                "eligibility_state": e["state"] if e else "UNKNOWN (no release artifacts)",
            })  # fmt: skip
        return {
            "platform": {
                "state": "UNKNOWN",
                "reason": "the platform state machine is not persisted",
            },
            "data": queries.data_health(c),
            "benchmarks": {
                "release": a.version if a else None,
                "series": series,
                "gate": "disabled",
            },  # fmt: skip
            "corporate_actions": queries.corporate_action_health(c),
            "research": queries.research_health(c),
            "strategies": {
                "persisted": False,
                "note": "strategy lifecycle states are not stored yet",
            },  # fmt: skip
            "system": {
                "database": "ok",
                "redis": "not configured",
                "api": "ok",
                "recent_ingestion": queries.ingestion_activity(c, 5),
            },  # fmt: skip
        }

    @app.get("/api/instruments")
    def instruments(
        c: Conn, q: Annotated[str, Query(min_length=1)], limit: int = Query(20, ge=1, le=100)
    ) -> list[dict[str, Any]]:
        return queries.search_instruments(c, q, limit)

    @app.get("/api/instruments/{instrument_id}")
    def instrument(c: Conn, instrument_id: int) -> dict[str, Any]:
        row = queries.instrument(c, instrument_id)
        if row is None:
            raise HTTPException(404, f"no instrument {instrument_id}")
        return {**row, "actions": queries.instrument_actions(c, instrument_id)}

    @app.get("/api/instruments/{instrument_id}/bars")
    def bars(
        c: Conn, instrument_id: int, start: date, end: date, adjust: Adjust = "none"
    ) -> dict[str, Any]:
        if end < start:
            raise HTTPException(422, "end before start")
        if queries.instrument(c, instrument_id) is None:
            raise HTTPException(404, f"no instrument {instrument_id}")
        return queries.instrument_bars(c, instrument_id, start, end, adjust)

    @app.get("/api/benchmarks")
    def benchmark_list(c: Conn) -> dict[str, Any]:
        a = arts()
        out = []
        for b in queries.benchmarks(c):
            out.append({**b, "eligibility": a.eligibility_of(b["id"]) if a else None})
        return {"release": a.version if a else None, "gate": "disabled", "benchmarks": out}

    @app.get("/api/benchmarks/{benchmark_id}")
    def benchmark(c: Conn, benchmark_id: int) -> dict[str, Any]:
        found = [b for b in queries.benchmarks(c) if b["id"] == benchmark_id]
        if not found:
            raise HTTPException(404, f"no benchmark {benchmark_id}")
        a = arts()
        return {
            **found[0], "release": a.version if a else None, "gate": "disabled",
            "eligibility": a.eligibility_of(benchmark_id) if a else None,
            "findings": a.findings_for(benchmark_id) if a else [],
            "validations": queries.benchmark_validations(c, benchmark_id),
            "session_calendar": (
                {
                    "calendar_version": a.session["calendar_version"],
                    "evidence": a.session["evidence"]["bhavcopy_range"],
                    "outcome_counts_all_series": a.session["observed_counts"],
                    "historical_session_hours": a.session["historical_session_hours"]["statement"],
                }
                if a
                else None
            ),
            "instrument_level_blocked_dates": (
                a.eligibility["instrument_level_blocked_dates"] if a else []
            ),
        }  # fmt: skip

    @app.get("/api/benchmarks/{benchmark_id}/levels")
    def benchmark_levels(
        c: Conn,
        benchmark_id: int,
        start: date | None = None,
        end: date | None = None,
        max_points: int = Query(1500, ge=10, le=10000),
    ) -> dict[str, Any]:
        if not any(b["id"] == benchmark_id for b in queries.benchmarks(c)):
            raise HTTPException(404, f"no benchmark {benchmark_id}")
        return {"levels": queries.benchmark_levels(c, benchmark_id, start, end, max_points)}

    @app.get("/api/backtests")
    def backtest_list(c: Conn) -> list[dict[str, Any]]:
        return queries.backtests(c)

    @app.get("/api/backtests/{run_id}")
    def backtest(c: Conn, run_id: int) -> dict[str, Any]:
        row = queries.backtest(c, run_id)
        if row is None:
            raise HTTPException(404, f"no backtest {run_id}")
        return row

    def latest_validations(c: psycopg.Connection) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for b in queries.benchmarks(c):
            history = queries.benchmark_validations(c, b["id"])
            out.append({"benchmark_id": b["id"], "latest": history[0] if history else None})
        return out

    @app.get("/api/system/activity")
    def activity(c: Conn) -> dict[str, Any]:
        return {
            "ingestion": queries.ingestion_activity(c, 50),
            "validations": latest_validations(c),
            "backtests": queries.backtests(c, 10),
            "jobs": {"persisted": False, "note": "job runtime and resource use are not recorded"},
        }  # fmt: skip

    return app
