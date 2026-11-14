# ruff: noqa: E501
"""Run a registered study's trials: every parameter combination of its grid, one after another, through the real engine.

For each combination: the strategy (looked up in the strategy registry) is built from the study's own settings and run over
the study's RESEARCH window only (from its start to the day before the holdout); prices come from the frozen Kite history,
costs from the stored broker schedules plus the study's slippage, and the stocks from the AMFI segments in force each day.
The trial is saved (metrics and daily returns) and counted in the registry, which is what the deflated Sharpe uses later.
The holdout is never read here. A run is resumable: combinations already done are skipped, a failed one is tried again.
It stops at the first failure and says why; nothing is retried silently."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from algo.api import artifacts
from algo.backtest import store
from algo.backtest.costs import schedule_store
from algo.backtest.costs.policy import CostPolicy, ScheduleCosts
from algo.backtest.costs.scaled import ScaledCosts
from algo.backtest.costs.slippage import SlippageModel
from algo.backtest.engine import BacktestConfig, RunResult, run_backtest
from algo.backtest.report import round_trips
from algo.backtest.validation import registry
from algo.backtest.validation.evidence import assemble
from algo.backtest.validation.gates import Thresholds, evaluate
from algo.backtest.validation.stats import sharpe_per_period
from algo.data import benchmark as benchmarks
from algo.data import benchmark_gate
from algo.data.reader import BarReader, PriceReader
from algo.research import fundamentals_book, holdout_lock, study_jobs, study_universe, verdict
from algo.research.holdout_lock import ResearchReader
from algo.research.study import THRESHOLDS_FILE, StudySpec
from algo.research.study_store import get_study
from algo.strategies.registry import STRATEGIES
from algo.strategies.trend_pullback import clear_indicator_cache

_ROOT = Path(__file__).resolve().parents[3]
GATE_FILE = _ROOT / "config" / "benchmark_gate.json"
DOCS_ROOT = _ROOT / "docs"  # the frozen benchmark releases

ALLOWED_COSTS = (
    "verified",
    "extracted_unverified",
    "assumed_backfill",
)  # the study records which statuses it relied on


class StudyRunError(ValueError):
    pass


class JobCancelled(Exception):
    """The owner asked this job to stop. It ends CANCELLED: not a failure, and nothing half-done is saved."""


def build(spec: StudySpec, combo: dict[str, Any], setup: Setup) -> Any:
    """The study's strategy for one parameter combination; a screener strategy also gets the study's screen (and the filings, if it reads them)."""
    cls, params_cls = STRATEGIES[spec.strategy_id]
    extra = (spec.screen, setup.fundamentals) if spec.screen else ()
    return cls(params_cls(**combo), setup.membership, *extra)


def cost_policy(conn: psycopg.Connection, spec: StudySpec) -> CostPolicy:
    s = spec.slippage
    return ScheduleCosts(
        schedule_store.load_book(conn, spec.broker, ALLOWED_COSTS),
        SlippageModel(
            base_bps=s.base_bps,
            participation_bps_per_pct=s.participation_bps_per_pct,
            volatility_fraction=s.volatility_fraction,
        ),
        product=spec.product,
        name=f"{spec.broker}-{spec.product.lower()}",
    )


def _ticker(conn: psycopg.Connection, run_id: int) -> Callable[[int, int, date], None]:
    """Reports the engine's day counter to the job row, at most every 2 seconds (and on the last day)."""
    last = [0.0]

    def tick(i: int, n: int, _day: date) -> None:
        now = time.monotonic()
        if i == n or now - last[0] >= 2.0:
            last[0] = now
            study_jobs.day_progress(conn, run_id, i, n)
            if study_jobs.stop_requested(conn, run_id):
                raise JobCancelled()

    return tick


def _returns(r: RunResult) -> list[float]:
    vals = [float(v) for _, v in r.equity]
    return [b / a - 1 for a, b in zip(vals, vals[1:], strict=False) if a > 0]


def _metrics(r: RunResult, returns: list[float]) -> dict[str, Any]:
    return {**{k: v for k, v in r.metrics.items()}, "trades": len(r.trades), "costs": float(sum(t.cost for t in r.trades)), "days": len(r.equity),
            "sharpe_per_period": sharpe_per_period(returns)}  # fmt: skip


@dataclass(frozen=True)
class Setup:
    """What every run of a study shares: the stocks held each day, the window, the costs and the price reader."""

    membership: Any
    coverage: list[dict[str, Any]]
    begin: date
    research_end: date
    policy: CostPolicy
    reader: PriceReader
    fundamentals: Any = None  # the filings a screener strategy reads (a FundamentalsBook), only when its screen uses them


def prepare(conn: psycopg.Connection, spec: StudySpec, exp: int, *, holdout: bool = False) -> Setup:
    """The shared setup. `holdout=True` is for the one-time test only: its window is the holdout (`research_end` is then its last day)."""
    try:
        lock = holdout_lock.require(conn)  # fails closed: no anchored lock, no study run
    except holdout_lock.HoldoutError as e:
        raise StudyRunError(f"research is locked: {e}") from e
    if spec.end > lock.development_end:
        raise StudyRunError(
            f"this study ends {spec.end}, inside the global research holdout (development ends {lock.development_end}): "
            "register a new version of it with an end on or before that day"
        )
    start, research_end = spec.start, spec.holdout_start - timedelta(days=1)
    if holdout:
        start, research_end = spec.holdout_start, spec.end
    else:
        registry.assert_research_window(conn, exp, research_end)
    membership, coverage = study_universe.build(conn, spec.universe, start, research_end)
    if not membership.ever():
        raise StudyRunError(
            "no stocks to trade: the chosen segments hold none we have Kite history for in this period"
        )
    first = membership.first_day()
    assert first is not None  # the universe is not empty
    return Setup(
        membership,
        coverage,
        max(start, first),  # nothing can be decided before anyone is a member
        research_end,
        cost_policy(conn, spec),
        # Studies read the FROZEN Kite history on purpose (locked by freeze and hash, Kite
        # visibility lag): they do not follow ALGO_PRICE_CUTOFF. Studying past the cutoff needs a
        # new freeze that includes the NSE bars, decided then.
        ResearchReader(BarReader(conn, source="kite", publish_lag=timedelta(0)), lock),
        fundamentals_book.load(conn, membership.ever(), start, research_end)
        if spec.screen is not None and spec.screen.needs_fundamentals()
        else None,
    )


def run_study(conn: psycopg.Connection, run_id: int, now: datetime) -> None:
    """Execute one queued (or claimed) run to the end. Never raises for a trial's own failure: the run records it."""
    run = study_jobs.get_run(conn, run_id)
    if run is None:
        raise StudyRunError(f"no such run {run_id}")
    if run["status"] not in ("QUEUED", "RUNNING"):
        return  # cancelled, or already finished
    exp = run["experiment_id"]
    study = get_study(conn, exp)
    assert study is not None
    spec = StudySpec.model_validate(study["spec"])
    try:
        setup = prepare(conn, spec, exp)
        coverage, begin, research_end = (
            setup.coverage,
            setup.begin,
            setup.research_end,
        )
        policy, reader = setup.policy, setup.reader
        combos = study["combinations"]
        already = study_jobs.done_hashes(conn, exp)
        todo = [c for c in combos if registry.params_hash(c) not in already]
        study_jobs.start(
            conn,
            run_id,
            len(combos),
            len(combos) - len(todo),
            {
                "universe_coverage": coverage,
                "research_window": [begin.isoformat(), research_end.isoformat()],
                "done_at_start": len(combos) - len(todo),
            },
            now,
        )
        clear_indicator_cache()  # a study run never serves a value computed under an earlier adjustment
        for k, combo in enumerate(todo):
            study_jobs.progress(
                conn,
                run_id,
                len(combos) - len(todo) + k,
                ", ".join(f"{n} {v}" for n, v in sorted(combo.items())),
            )
            params_hash = registry.params_hash(combo)
            t0 = time.monotonic()
            try:
                cfg = BacktestConfig(
                    start=begin,
                    end=research_end,
                    initial_cash=spec.capital,
                    cost=policy,
                    min_order_value=spec.min_order_value,
                    max_order_value=spec.max_order_value,
                )
                result = run_backtest(
                    conn, build(spec, combo, setup), cfg, reader=reader,
                    on_day=_ticker(conn, run_id),
                )  # fmt: skip
            except JobCancelled:
                raise
            except Exception as e:  # recorded with its reason, never retried silently
                study_jobs.save_trial(
                    conn,
                    exp,
                    combo,
                    params_hash,
                    "FAILED",
                    now,
                    error=f"{type(e).__name__}: {e}",
                    seconds=time.monotonic() - t0,
                )
                raise StudyRunError(
                    f"{', '.join(f'{n} {v}' for n, v in sorted(combo.items()))}: {type(e).__name__}: {e}"
                ) from e
            returns = _returns(result)
            backtest_run = store.save_run(conn, result, now)
            registry.record_trial(conn, exp, combo, sharpe_per_period(returns), backtest_run, now)
            study_jobs.save_trial(
                conn,
                exp,
                combo,
                params_hash,
                "DONE",
                now,
                metrics=_metrics(result, returns),
                returns=returns,
                backtest_run=backtest_run,
                seconds=time.monotonic() - t0,
            )
        study_jobs.progress(conn, run_id, len(combos), None)
        study_jobs.finish(conn, run_id, "DONE", now)
    except JobCancelled:
        study_jobs.finish(conn, run_id, "CANCELLED", now)
    except StudyRunError as e:
        study_jobs.finish(conn, run_id, "FAILED", now, str(e))


def _fills(conn: psycopg.Connection, run_id: int) -> list[Any]:
    return [
        tuple(r)
        for r in conn.execute(
            "SELECT seq, day, instrument_id, side, qty, price, cost FROM backtest_trade WHERE run_id=%s",
            (run_id,),
        )
    ]


def _thresholds(spec: StudySpec) -> tuple[Thresholds, str]:
    """The owner's twelve numbers locked into the study, with the status of the thresholds file they came from."""
    status = json.loads(THRESHOLDS_FILE.read_text()).get("status", "")
    return Thresholds(**{k: float(v) for k, v in spec.thresholds.items()}), status


def _benchmark(
    conn: psycopg.Connection, spec: StudySpec, sessions: list[date]
) -> tuple[list[float] | None, str | None]:
    """The study's index returns on exactly these days, or (None, why not): the gates that need it then fail for missing evidence."""
    try:
        row = conn.execute(
            "SELECT benchmark_id FROM benchmark WHERE name=%s", (spec.benchmark,)
        ).fetchone()
        if row is None:
            raise benchmarks.BenchmarkError(f"there is no benchmark called {spec.benchmark!r}")
        why = benchmark_gate.blocker(
            artifacts.load(DOCS_ROOT), row[0], benchmark_gate.is_enabled(GATE_FILE)
        )
        if why:
            raise benchmarks.BenchmarkError(why)
        if not benchmarks.validated(conn, row[0]):
            raise benchmarks.BenchmarkError(
                f"{spec.benchmark} has no passing validation for its stored data"
            )
        return benchmarks.gate_returns(conn, row[0], sessions), None
    except benchmarks.BenchmarkError as e:
        return None, str(e)


def run_verdict(conn: psycopg.Connection, run_id: int, now: datetime) -> None:
    """Judge a finished study: walk-forward over the stored trials, two more engine runs for the cost and capacity stress,
    then every gate. The result is a validation report saved against the chosen setting's run. Never touches the holdout."""
    run = study_jobs.get_run(conn, run_id)
    if run is None:
        raise StudyRunError(f"no such run {run_id}")
    if run["status"] not in ("QUEUED", "RUNNING"):
        return
    exp = run["experiment_id"]
    study = get_study(conn, exp)
    assert study is not None
    spec = StudySpec.model_validate(study["spec"])
    try:
        combos = study["combinations"]
        done = conn.execute(
            "SELECT params_hash, backtest_run FROM study_trial WHERE experiment_id=%s AND status='DONE'",
            (exp,),
        ).fetchall()
        if len(done) < len(combos):
            raise StudyRunError(
                f"only {len(done)} of {len(combos)} trials are finished: run all trials first"
            )
        run_of: dict[str, int] = dict(done)
        returns = study_jobs.trial_returns(conn, exp)
        sessions = [
            r[0]
            for r in conn.execute(
                "SELECT day FROM backtest_equity WHERE run_id=%s ORDER BY day",
                (next(iter(run_of.values())),),
            )
        ]
        bench, bench_note = _benchmark(conn, spec, sessions)
        a = verdict.analyse(sessions, combos, returns, spec.grid, bench)
        base_run = run_of[registry.params_hash(a.base)]
        study_jobs.start(conn, run_id, 2, 0, {"chosen": a.base}, now)
        setup = prepare(conn, spec, exp)

        def strategy_of() -> Any:
            return build(spec, a.base, setup)

        def stress(label: str, cost: CostPolicy, cash: Decimal) -> tuple[list[float], int]:
            study_jobs.progress(conn, run_id, 0 if label == "2x costs" else 1, label)
            cfg = BacktestConfig(
                start=setup.begin, end=setup.research_end, initial_cash=cash, cost=cost,
                min_order_value=spec.min_order_value, max_order_value=spec.max_order_value,
            )  # fmt: skip
            result = run_backtest(
                conn, strategy_of(), cfg, reader=setup.reader, on_day=_ticker(conn, run_id)
            )
            return _returns(result), store.save_run(conn, result, now, f"verdict: {label}")

        r2, run_2x = stress("2x costs", ScaledCosts(setup.policy, Decimal(2)), spec.capital)
        r3, run_3x = stress("3x capital", setup.policy, spec.capital * spec.capacity_multiple)
        thresholds, status = _thresholds(spec)
        evidence = assemble(
            verdict.inputs(
                a,
                n_trials=registry.trial_count(conn, exp),
                trial_sharpes=registry.trial_sharpes(conn, exp),
                trial_returns=[returns[registry.params_hash(c)] for c in combos],
                plateau_tolerance=thresholds.plateau_tolerance,
                returns_2x_costs=r2,
                returns_3x_capital=r3,
                trips=round_trips(_fills(conn, base_run), store.run_splits(conn, base_run)),
            )
        )
        registry.save_report(
            conn, exp, base_run, evaluate(evidence, thresholds, status), evidence,
            registry.trial_count(conn, exp), now,
            refs={
                "chosen": a.base, "benchmark": spec.benchmark, "benchmark_note": bench_note,
                "windows": a.windows, "walk_forward": {"train": verdict.TRAIN, "test": verdict.TEST, "embargo": verdict.EMBARGO},
                "cost_2x_run": run_2x, "capital_run": run_3x, "capital_multiple": str(spec.capacity_multiple),
            },
        )  # fmt: skip
        study_jobs.progress(conn, run_id, 2, None)
        study_jobs.finish(conn, run_id, "DONE", now)
    except JobCancelled:
        study_jobs.finish(conn, run_id, "CANCELLED", now)
    except (StudyRunError, verdict.VerdictError) as e:
        study_jobs.finish(conn, run_id, "FAILED", now, str(e))


def run_holdout(conn: psycopg.Connection, run_id: int, now: datetime) -> None:
    """The one-time final test: the settings the passed verdict chose, run over the holdout days the study never saw, judged against
    the owner's thresholds for Sharpe, drawdown and the index. Opening the holdout is claimed in the same transaction as saving
    the result, so a second attempt (or a crash after the claim) can never produce a second look."""
    run = study_jobs.get_run(conn, run_id)
    if run is None:
        raise StudyRunError(f"no such run {run_id}")
    if run["status"] not in ("QUEUED", "RUNNING"):
        return
    exp = run["experiment_id"]
    study = get_study(conn, exp)
    assert study is not None
    spec = StudySpec.model_validate(study["spec"])
    try:
        report = study_jobs.latest_report(conn, exp)
        if report is None or not report["passed"]:
            raise StudyRunError(
                "the holdout opens only after a research verdict that passed every check"
            )
        if study["holdout_opened_at"] is not None:
            raise StudyRunError("the holdout of this study has already been opened")
        chosen = report["refs"]["chosen"]
        setup = prepare(conn, spec, exp, holdout=True)
        study_jobs.start(conn, run_id, 1, 0, {"chosen": chosen}, now)
        study_jobs.progress(conn, run_id, 0, "the holdout days")
        cfg = BacktestConfig(
            start=setup.begin, end=setup.research_end, initial_cash=spec.capital, cost=setup.policy,
            min_order_value=spec.min_order_value, max_order_value=spec.max_order_value,
        )  # fmt: skip
        result = run_backtest(
            conn, build(spec, chosen, setup), cfg, reader=setup.reader,
            on_day=_ticker(conn, run_id),
        )  # fmt: skip
        returns = _returns(result)
        bench, note = _benchmark(conn, spec, [d for d, _ in result.equity])
        thresholds, _ = _thresholds(spec)
        gates, evidence = verdict.holdout_gates(returns, bench, thresholds)
        saved = store.save_run(conn, result, now, "holdout")
        refs = {"chosen": chosen, "benchmark": spec.benchmark, "benchmark_note": note,
                "window": [setup.begin.isoformat(), setup.research_end.isoformat()], "verdict_report": report["report_id"]}  # fmt: skip
        with conn.transaction():
            registry.open_holdout(conn, exp, saved, now)
            conn.execute(
                "INSERT INTO study_holdout (experiment_id, run_id, passed, evidence, gates, refs, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (
                    exp,
                    saved,
                    all(g["passed"] for g in gates),
                    Jsonb(evidence),
                    Jsonb(gates),
                    Jsonb(refs),
                    now,
                ),
            )
        study_jobs.progress(conn, run_id, 1, None)
        study_jobs.finish(conn, run_id, "DONE", now)
    except JobCancelled:
        study_jobs.finish(conn, run_id, "CANCELLED", now)
    except (StudyRunError, verdict.VerdictError, registry.HoldoutAlreadyOpened) as e:
        study_jobs.finish(conn, run_id, "FAILED", now, str(e))


def execute(conn: psycopg.Connection, run_id: int, now: datetime) -> None:
    """Run whatever kind of job this is."""
    run = study_jobs.get_run(conn, run_id)
    kind = run["kind"] if run else "trials"
    {"verdict": run_verdict, "holdout": run_holdout}.get(kind, run_study)(conn, run_id, now)
