# ruff: noqa: E501
"""The evaluator behind the ONE holdout batch (`holdout_batch`): it runs each frozen candidate's chosen settings over the global holdout and
judges the holdout gates, and it builds the manifest from the registry so family ids and trial counts are read, never typed in.

Each candidate is judged by `verdict.holdout_gates_v3` (policy v3 section 2): the Monte Carlo bootstrap test at 0.05 / 30 with the candidate's own seed committed at freeze,
plus the Sharpe, drawdown-against-the-index and edge-over-the-index floors. A candidate that cannot be evaluated (no stocks to trade in the window, missing data, an error in
the judging) gets INSUFFICIENT_EVIDENCE on every gate: never a pass, and not a plain fail either. Not yet checked here: that the equity curve covers every session of the
window (needs the trading-calendar trace of policy section 10 step 0) and the capability-scoped data access of section 7."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

import psycopg

from algo.backtest.engine import BacktestConfig, run_backtest
from algo.backtest.validation import registry
from algo.data.reader import BarReader
from algo.research import fundamentals_book, holdout_batch, holdout_lock, study_universe, verdict
from algo.research.holdout_batch import BatchError, Candidate, Capability, Manifest, Results
from algo.research.study import StudySpec
from algo.research.study_runner import (
    Setup,
    StudyRunError,
    _benchmark,
    _returns,
    _thresholds,
    build,
    cost_policy,
)

HOLDOUT_GATES = verdict.V3_GATES
Readers = Callable[
    [datetime], Any
]  # known_at -> the unwrapped price reader a candidate's study was pinned to


def build_manifest(
    conn: psycopg.Connection,
    batch_id: int,
    experiment_ids: list[int],
    *,
    correction_method: str = "bonferroni-30",
    correction_version: str = holdout_batch.METHODOLOGY_VERSION,
) -> Manifest:
    """One candidate per study, from what the registry holds: its sealed dataset, its newest PASSED development report, its family and
    the family's whole trial count. Anything missing is named; nothing is guessed."""
    lock = holdout_lock.require(conn)
    candidates: list[Candidate] = []
    trials: dict[str, int] = {}
    problems: list[str] = []
    for exp in experiment_ids:
        row = conn.execute(
            "SELECT e.study_sha256, e.family_id, e.study, d.dataset_sha256 FROM experiment e LEFT JOIN study_dataset d USING (experiment_id) WHERE e.experiment_id=%s",
            (exp,),
        ).fetchone()
        if row is None or row[0] is None:
            problems.append(f"study {exp} is not a registered study")
            continue
        sha, family, study, dataset = row
        report = conn.execute(
            "SELECT report_id, refs FROM validation_report WHERE experiment_id=%s AND passed ORDER BY report_id DESC LIMIT 1",
            (exp,),
        ).fetchone()
        chosen = ((report[1] or {}).get("chosen") if report else None) or None
        if family is None:
            problems.append(f"study {exp} has no research family")
        if dataset is None:
            problems.append(f"study {exp} has not sealed its dataset (it has never been run)")
        if report is None or not chosen:
            problems.append(f"study {exp} has no passed development verdict with chosen settings")
        if family is None or dataset is None or report is None or not chosen:
            continue
        spec = (study or {}).get("spec") or {}
        code = (study or {}).get("code") or {}
        candidates.append(
            Candidate(
                f"study-{exp}",
                str(family),
                f"{spec.get('strategy_id', 'strategy')}@{code.get('commit', 'unknown')}",
                registry.params_hash(chosen),
                dataset,
                sha,
                report[0],
            )  # fmt: skip
        )
        trials[str(family)] = registry.family_trial_count(conn, family)
    if problems:
        raise BatchError("the manifest cannot be built: " + "; ".join(problems))
    return Manifest(
        batch_id, tuple(candidates), trials, lock.holdout_start, lock.holdout_end,
        correction_method, correction_version, holdout_batch.EVALUATOR_VERSION,
    )  # fmt: skip


def _sessions(conn: Any, begin: date, end: date) -> set[date]:
    """The trading sessions of the window: every date the source bars trade on (the platform's own calendar of the history)."""
    rows = conn.execute(
        "SELECT DISTINCT (ts AT TIME ZONE 'Asia/Kolkata')::date FROM bar_1d WHERE source='kite'"
        " AND ts >= %s::date - 1 AND ts < %s::date + 2",
        (begin, end),
    ).fetchall()
    return {r[0] for r in rows if begin <= r[0] <= end}


def _candidate(
    conn: psycopg.Connection, c: Candidate, m: Manifest, readers: Readers
) -> tuple[dict[str, str], dict[str, Any]]:
    """(verdict per gate, owner-only detail) for one candidate."""
    row = conn.execute(
        "SELECT experiment_id, study FROM experiment WHERE study_sha256=%s ORDER BY experiment_id LIMIT 1",
        (c.study_sha256,),
    ).fetchone()
    if row is None:
        raise BatchError(f"no registered study has study_sha256 {c.study_sha256}")
    exp, doc = row
    spec = StudySpec.model_validate((doc or {})["spec"])
    refs = conn.execute(
        "SELECT refs FROM validation_report WHERE report_id=%s", (c.validation_report_id,)
    ).fetchone()
    chosen = (refs[0] or {}).get("chosen") if refs else None
    if not chosen:
        raise BatchError(
            f"candidate {c.candidate_id}: its development report names no chosen settings"
        )
    known_at = datetime.fromisoformat((doc or {})["known_at"])
    membership, coverage = study_universe.build(conn, spec.universe, m.date_from, m.date_to)
    if not membership.ever():
        raise StudyRunError("no stocks to trade in the holdout window")
    first = membership.first_day()
    assert first is not None
    begin = max(m.date_from, first)
    setup = Setup(
        membership, coverage, begin, m.date_to, cost_policy(conn, spec), readers(known_at),
        fundamentals_book.load(conn, membership.ever(), begin, m.date_to, lag=timedelta(days=spec.filing_lag_days)) if spec.screen is not None and spec.screen.needs_fundamentals() else None,
    )  # fmt: skip
    cfg = BacktestConfig(
        start=begin, end=m.date_to, initial_cash=spec.capital, cost=setup.policy,
        min_order_value=spec.min_order_value, max_order_value=spec.max_order_value,
        trade_stop=spec.trade_stop, stop_cooldown_days=spec.stop_cooldown_days,
    )  # fmt: skip
    result = run_backtest(conn, build(spec, chosen, setup), cfg, reader=setup.reader)
    days = {d for d, _ in result.equity}
    missing = sorted(_sessions(conn, begin, m.date_to) - days)
    if (
        not days or missing
    ):  # policy section 2: the curve must cover every session of the window, or there is no evidence
        raise StudyRunError(
            f"the equity curve misses {len(missing)} session(s) of the holdout window"
            + (f" (first {missing[0]})" if missing else "")
        )
    bench, note = _benchmark(conn, spec, [d for d, _ in result.equity])
    thresholds, _ = _thresholds(spec)
    gates, evidence = verdict.holdout_gates_v3(
        _returns(result), bench, thresholds, seed=int(m.seeds[c.candidate_id], 16)
    )
    return (
        {g["name"]: g["status"] for g in gates},
        {"chosen": chosen, "window": [begin.isoformat(), m.date_to.isoformat()], "benchmark": spec.benchmark, "benchmark_note": note, "evidence": evidence, "gates": gates},
    )  # fmt: skip


def evaluate(cap: Capability, m: Manifest) -> Results:
    """The `run` the batch calls once: every candidate judged over the global holdout. A candidate that cannot be run gets
    INSUFFICIENT_EVIDENCE on every gate, with the reason in the owner-only report."""
    readers: Readers = cap.reader
    conn = cap.connection  # guarded: source inputs and the study's own record only
    verdicts: dict[tuple[str, str], str] = {}
    detail: dict[str, Any] = {}
    for c in m.candidates:
        try:
            per_gate, info = _candidate(conn, c, m, readers)
        except (StudyRunError, verdict.VerdictError) as e:
            per_gate, info = {g: "INSUFFICIENT_EVIDENCE" for g in HOLDOUT_GATES}, {"error": str(e)}
        for gate, v in per_gate.items():
            verdicts[(c.candidate_id, gate)] = v
        detail[c.candidate_id] = info
    return Results(
        verdicts,
        {
            "evaluator": holdout_batch.EVALUATOR_VERSION, "manifest_sha256": m.sha256,
            "window": [m.date_from.isoformat(), m.date_to.isoformat()], "family_trials": dict(m.family_trials),
            "correction": [m.correction_method, m.correction_version], "candidates": detail,
        },
    )  # fmt: skip


def run_batch(conn: psycopg.Connection, batch_id: int, now: datetime) -> None:
    """Evaluate the frozen batch once (or resume an interrupted evaluation): the single path that ever reads the holdout."""

    def factory(guarded: Any) -> Readers:
        return lambda known_at: BarReader(
            guarded, source="kite", publish_lag=timedelta(0), known_at=known_at
        )

    holdout_batch.evaluate(conn, batch_id, evaluate, factory, now)
