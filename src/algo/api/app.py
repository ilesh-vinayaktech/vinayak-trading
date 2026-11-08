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
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from algo.api import artifacts, freshness, queries
from algo.core.clock import Clock, SystemClock
from algo.indicators.catalog import IndicatorError, parse_spec

Adjust = Literal["none", "split", "total_return"]

# Every connection is read-only and bounded: the API cannot write and a runaway query is cut.
DB_OPTIONS = (
    "-c default_transaction_read_only=on -c statement_timeout=15000"
    " -c idle_in_transaction_session_timeout=30000"
)
MAX_RANGE_DAYS = 366 * 40
MAX_INDICATORS = 12
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Resource-Policy": "same-site",
}


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Response:
        response: Response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers[k] = v
        return response


def get_conn(request: Request) -> Iterator[psycopg.Connection]:
    with psycopg.connect(request.app.state.dsn, options=DB_OPTIONS, connect_timeout=5) as c:
        yield c


Conn = Annotated[psycopg.Connection, Depends(get_conn)]


def create_app(
    dsn: str,
    docs_root: Path,
    origins: tuple[str, ...] = ("http://localhost:3000",),
    *,
    interactive_docs: bool = False,
    clock: Clock | None = None,
    sessions_file: Path | None = None,
) -> FastAPI:
    clock = clock or SystemClock()
    sessions_path = sessions_file or docs_root.parent / "config" / "exchange_sessions.json"
    app = FastAPI(
        title="Vinayak Trading Research Console API",
        version="0.1",
        docs_url="/docs" if interactive_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if interactive_docs else None,
    )
    app.add_middleware(SecurityHeaders)
    app.state.dsn = dsn
    app.add_middleware(CORSMiddleware, allow_origins=list(origins), allow_methods=["GET"],
                       allow_headers=["*"])  # fmt: skip

    def arts() -> artifacts.Artifacts | None:
        return artifacts.load(docs_root)  # re-read: a new release shows without a restart

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        try:
            with psycopg.connect(dsn, options=DB_OPTIONS, connect_timeout=3) as c:
                c.execute("SELECT 1")
            db = "ok"
        except psycopg.Error as e:
            db = f"error: {type(e).__name__}"
        return {"api": "ok", "database": db, "redis": "not configured"}

    def fresh(c: psycopg.Connection) -> dict[str, Any] | None:
        last = queries.data_health(c)["last_date"]
        if last is None:
            return None
        return freshness.assess(date.fromisoformat(last), clock.now(), queries.known_holidays(c))

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
            "data": {**queries.data_health(c), "freshness": fresh(c)},
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
                "recent_ingestion": queries.ingestion_activity(c, 5)["items"],
            },  # fmt: skip
        }

    @app.get("/api/instruments")
    def instruments(
        c: Conn,
        q: Annotated[str, Query(min_length=1, max_length=64)],
        limit: int = Query(20, ge=1, le=100),
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
        if (end - start).days > MAX_RANGE_DAYS:
            raise HTTPException(422, "range longer than 40 years")
        if queries.instrument(c, instrument_id) is None:
            raise HTTPException(404, f"no instrument {instrument_id}")
        return queries.instrument_bars(c, instrument_id, start, end, adjust)

    @app.get("/api/indicators")
    def indicator_list() -> dict[str, Any]:
        return {"indicators": queries.indicator_catalog()}

    @app.get("/api/instruments/{instrument_id}/indicators")
    def indicators(
        c: Conn,
        instrument_id: int,
        start: date,
        end: date,
        names: Annotated[str, Query(min_length=1, max_length=400)],
        adjust: Adjust = "none",
    ) -> dict[str, Any]:
        if end < start:
            raise HTTPException(422, "end before start")
        if (end - start).days > MAX_RANGE_DAYS:
            raise HTTPException(422, "range longer than 40 years")
        specs = [n for n in names.split(",") if n.strip()]
        if not specs or len(specs) > MAX_INDICATORS:
            raise HTTPException(422, f"ask for between 1 and {MAX_INDICATORS} indicators")
        try:
            for spec in specs:
                parse_spec(spec)
        except IndicatorError as e:
            raise HTTPException(422, str(e)) from e
        if queries.instrument(c, instrument_id) is None:
            raise HTTPException(404, f"no instrument {instrument_id}")
        return queries.indicator_series(c, instrument_id, start, end, adjust, specs)

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
                    "all_series": artifacts.describe_outcomes(a.session["observed_counts"]),
                    "this_series": a.session_dependencies(benchmark_id),
                    "listed_special_sessions": artifacts.session_properties(
                        sessions_path, a.release
                    ),
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
        return queries.benchmark_levels(c, benchmark_id, start, end, max_points)

    @app.get("/api/backtests")
    def backtest_list(
        c: Conn, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)
    ) -> dict[str, Any]:
        return queries.backtests(c, limit, offset)

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
            out.append(
                {
                    "benchmark_id": b["id"],
                    "name": b["name"],
                    "latest": history[0] if history else None,
                }
            )
        return out

    @app.get("/api/system/activity")
    def activity(
        c: Conn, limit: int = Query(25, ge=1, le=200), offset: int = Query(0, ge=0)
    ) -> dict[str, Any]:
        return {
            "ingestion": queries.ingestion_activity(c, limit, offset),
            "validations": latest_validations(c),
            "backtests": queries.backtests(c, 10)["items"],
            "jobs": {"persisted": False, "note": "job runtime and resource use are not recorded"},
        }  # fmt: skip

    return app
