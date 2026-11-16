# ruff: noqa: E501
"""Pre-registration and the trial counter. A hypothesis, its parameter ranges and a holdout window
are written down BEFORE any trial; every distinct configuration tried is counted (that N feeds the
Deflated Sharpe); the holdout can be opened exactly once."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from algo.backtest.validation.gates import Evidence, Report
from algo.core.clock import require_utc


class RegistryError(Exception):
    pass


class HoldoutAlreadyOpened(RegistryError):
    pass


def params_hash(params: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()


def register(
    conn: psycopg.Connection,
    *,
    name: str,
    strategy_id: str,
    hypothesis: str,
    style: str,
    param_ranges: Mapping[str, Sequence[float]],
    holdout: tuple[date, date],
    now: datetime,
    study: Mapping[str, Any] | None = None,
    owner_user_id: UUID | None = None,
    family_id: int | None = None,
) -> int:
    """`study`: the owner's full study settings (algo.research.study); stored with a checksum
    and locked with the rest of the row (migration 045)."""
    if not hypothesis.strip():
        raise RegistryError("a hypothesis is required before any trial")
    for k, r in param_ranges.items():
        if len(r) != 2 or r[0] > r[1]:
            raise RegistryError(f"range for {k!r} must be [low, high] with low <= high")
    row = conn.execute(
        "INSERT INTO experiment (name,strategy_id,hypothesis,style,param_ranges,holdout_start,"
        "holdout_end,registered_at,study,study_sha256,owner_user_id,family_id)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING experiment_id",
        (
            name,
            strategy_id,
            hypothesis,
            style,
            Jsonb(param_ranges),
            *holdout,
            require_utc(now),
            None if study is None else Jsonb(dict(study)),
            None if study is None else params_hash(study),
            owner_user_id,
            family_id,
        ),  # fmt: skip
    ).fetchone()
    assert row is not None
    return int(row[0])


def _experiment(conn: psycopg.Connection, exp_id: int) -> tuple[dict[str, Any], date, date]:
    row = conn.execute(
        "SELECT param_ranges, holdout_start, holdout_end FROM experiment WHERE experiment_id=%s",
        (exp_id,),
    ).fetchone()
    if row is None:
        raise RegistryError(f"no experiment {exp_id}")
    return row[0], row[1], row[2]


def record_trial(
    conn: psycopg.Connection,
    exp_id: int,
    params: Mapping[str, Any],
    sharpe: float | None,
    run_id: int | None,
    now: datetime,
) -> int:
    """Count one configuration. Re-running the same params is not a new trial. Returns N."""
    ranges, _, _ = _experiment(conn, exp_id)
    for k, v in params.items():
        if k not in ranges:
            raise RegistryError(f"parameter {k!r} was not pre-registered")
        lo, hi = ranges[k]
        if not lo <= v <= hi:
            raise RegistryError(f"parameter {k!r}={v} is outside the registered range [{lo}, {hi}]")
    conn.execute(
        "INSERT INTO experiment_trial (experiment_id,params,params_hash,sharpe,run_id,recorded_at)"
        " VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (experiment_id,params_hash) DO NOTHING",
        (exp_id, Jsonb(params), params_hash(params), sharpe, run_id, require_utc(now)),
    )
    return trial_count(conn, exp_id)


def trial_count(conn: psycopg.Connection, exp_id: int) -> int:
    row = conn.execute(
        "SELECT count(*) FROM experiment_trial WHERE experiment_id=%s", (exp_id,)
    ).fetchone()
    assert row is not None
    return int(row[0])


def create_family(
    conn: psycopg.Connection,
    *,
    name: str,
    hypothesis: str,
    justification: str,
    created_by: UUID | None,
    now: datetime,
) -> int:
    """Start a research family: an explicit decision, never a side effect of registering a study. The justification says what makes
    the hypothesis genuinely different from every existing family (otherwise it belongs in one of them)."""
    if not name.strip():
        raise RegistryError("a family needs a name")
    if len(hypothesis.strip()) < 20:
        raise RegistryError("the family's hypothesis needs at least 20 characters")
    if len(justification.strip()) < 20:
        raise RegistryError(
            "the justification needs at least 20 characters: say what makes this genuinely different from every existing family"
        )
    try:
        row = conn.execute(
            "INSERT INTO research_family (name, hypothesis, justification, created_by, created_at)"
            " VALUES (%s,%s,%s,%s,%s) RETURNING family_id",
            (name.strip(), hypothesis.strip(), justification.strip(), created_by, require_utc(now)),
        ).fetchone()
    except psycopg.errors.UniqueViolation as e:
        raise RegistryError(f"a family called {name.strip()!r} already exists") from e
    assert row is not None
    return int(row[0])


def list_families(conn: psycopg.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT f.family_id, f.name, f.hypothesis, f.justification, f.created_at,"
        " (SELECT count(*) FROM experiment e WHERE e.family_id = f.family_id),"
        " (SELECT count(*) FROM experiment_trial t JOIN experiment e USING (experiment_id) WHERE e.family_id = f.family_id)"
        " FROM research_family f ORDER BY f.family_id"
    ).fetchall()
    return [
        {
            "family_id": r[0],
            "name": r[1],
            "hypothesis": r[2],
            "justification": r[3],
            "created_at": r[4],
            "studies": r[5],
            "trials": r[6],
        }
        for r in rows
    ]


def experiment_family(conn: psycopg.Connection, exp_id: int) -> int | None:
    row = conn.execute(
        "SELECT family_id FROM experiment WHERE experiment_id=%s", (exp_id,)
    ).fetchone()
    return None if row is None or row[0] is None else int(row[0])


# Features that measure the same underlying idea: strategies ranked by any of them are tries of ONE hypothesis, so their trials count together (review 2026-11-16, section 3.1).
FACTORS: dict[str, tuple[str, ...]] = {
    "volatility": ("vol_20d", "vol_60d", "range_vol_20d", "atr_14d", "atr_pct_14d"),
    "momentum": ("ret_60d", "ret_120d", "ret_252d", "dist_high_252d", "dist_low_252d"),
    "short_term_reversal": (
        "ret_1d",
        "ret_5d",
        "ret_20d",
        "dist_sma_50d",
        "dist_sma_200d",
        "rsi_14d",
    ),
    "liquidity": ("traded_value_20d", "volume_ratio_20_60d"),
}
FACTOR_OF = {f: name for name, fs in FACTORS.items() for f in fs}


def hypothesis_key(strategy_id: str, study: Mapping[str, Any] | None) -> str:
    """The idea an experiment tests: for a generated definition, the factor of the feature it RANKS by (so its weekly and monthly versions, and 20- and 60-day variants, are tries of one idea);
    for a coded strategy, the strategy itself."""
    definition = ((study or {}).get("spec") or {}).get("definition")
    if strategy_id == "dsl" and definition:
        feature = str((definition.get("ranking") or {}).get("feature", ""))
        return "dsl:" + FACTOR_OF.get(feature, feature)
    return strategy_id


def _window(study: Mapping[str, Any] | None) -> tuple[str, str] | None:
    spec = (study or {}).get("spec") or {}
    return (str(spec["start"]), str(spec["end"])) if "start" in spec and "end" in spec else None


def _try_id(eid: int, strategy_id: str, study: Mapping[str, Any] | None) -> tuple[Any, ...]:
    """What makes two trials the same try: the same definition (or coded strategy), research window, per-trade stop and cooldown. Without a definition id, the experiment itself."""
    spec = (study or {}).get("spec") or {}
    d = spec.get("definition") or {}
    who = (d.get("strategy_id"), d.get("version")) if d.get("strategy_id") else (strategy_id, eid)
    return (who, _window(study), spec.get("trade_stop"), spec.get("stop_cooldown_days"))


def deflation_trials(conn: psycopg.Connection, exp_id: int) -> tuple[int, list[float]]:
    """(N, per-trial Sharpes) the multiple-testing correction uses for this experiment (review 2026-11-16, section 3.1).
    N counts EVERY trial of the same idea (same research family, same hypothesis key) on any window, so trying a variant again or on another window never resets the penalty.
    The spread of the Sharpes comes only from trials of that idea on the SAME research window: other ideas, other windows and coded strategies sharing a catch-all family
    would otherwise inflate it and make every strategy fail. An experiment outside any family counts only its own."""
    family = experiment_family(conn, exp_id)
    if family is None:
        return trial_count(conn, exp_id), trial_sharpes(conn, exp_id)
    rows = conn.execute(
        "SELECT experiment_id, strategy_id, study FROM experiment WHERE family_id=%s", (family,)
    ).fetchall()
    mine = next(((sid, study) for eid, sid, study in rows if eid == exp_id), None)
    if mine is None:
        return trial_count(conn, exp_id), trial_sharpes(conn, exp_id)
    key, window = hypothesis_key(mine[0], mine[1]), _window(mine[1])
    same = [eid for eid, sid, study in rows if hypothesis_key(sid, study) == key]
    comparable = {eid for eid, sid, study in rows if eid in same and _window(study) == window}
    ident = {eid: _try_id(eid, sid, study) for eid, sid, study in rows}
    seen: set[tuple[Any, str]] = set()
    n = 0
    sharpes: list[float] = []
    for eid, params_hash, sharpe in conn.execute(
        "SELECT experiment_id, params_hash, sharpe FROM experiment_trial WHERE experiment_id = ANY(%s) ORDER BY trial_id",
        (same,),
    ):
        key_ = (ident[eid], params_hash)
        if key_ in seen:  # the same definition, window and setting tried again is one try, not two
            continue
        seen.add(key_)
        n += 1
        if eid in comparable and sharpe is not None:
            sharpes.append(float(sharpe))
    return n, sharpes


def family_trial_count(conn: psycopg.Connection, family_id: int) -> int:
    """Every trial of every study in the family. A re-registered study's trials add to the family's, never reset it (so the count is
    deliberately on the high side: the same settings tried again are counted again)."""
    row = conn.execute(
        "SELECT count(*) FROM experiment_trial t JOIN experiment e USING (experiment_id) WHERE e.family_id=%s",
        (family_id,),
    ).fetchone()
    assert row is not None
    return int(row[0])


def family_trial_sharpes(conn: psycopg.Connection, family_id: int) -> list[float]:
    """Per-period Sharpe of every defined trial in the family (the deflated Sharpe's variance across all the tries)."""
    return [
        float(r[0])
        for r in conn.execute(
            "SELECT t.sharpe FROM experiment_trial t JOIN experiment e USING (experiment_id)"
            " WHERE e.family_id=%s AND t.sharpe IS NOT NULL ORDER BY t.trial_id",
            (family_id,),
        )
    ]


def trial_sharpes(conn: psycopg.Connection, exp_id: int) -> list[float]:
    """Per-period Sharpe of every trial with a defined one (the DSR's cross-trial variance)."""
    return [
        float(r[0])
        for r in conn.execute(
            "SELECT sharpe FROM experiment_trial WHERE experiment_id=%s AND sharpe IS NOT NULL"
            " ORDER BY trial_id",
            (exp_id,),
        )
    ]


def assert_research_window(conn: psycopg.Connection, exp_id: int, last_day: date) -> None:
    """Development runs must end before the holdout starts."""
    _, h_start, _ = _experiment(conn, exp_id)
    if last_day >= h_start:
        raise RegistryError(f"run ends {last_day}, inside the holdout that starts {h_start}")


def open_holdout(conn: psycopg.Connection, exp_id: int, run_id: int, now: datetime) -> None:
    """Atomically claim the one-time right to look at the holdout."""
    _experiment(conn, exp_id)
    cur = conn.execute(
        "UPDATE experiment SET holdout_opened_at=%s, holdout_run_id=%s"
        " WHERE experiment_id=%s AND holdout_opened_at IS NULL",
        (require_utc(now), run_id, exp_id),
    )
    if cur.rowcount != 1:
        raise HoldoutAlreadyOpened(f"experiment {exp_id}: the holdout was already opened")


def save_report(
    conn: psycopg.Connection,
    exp_id: int,
    run_id: int,
    report: Report,
    evidence: Evidence,
    n_trials: int,
    now: datetime,
    refs: Mapping[str, Any] | None = None,
) -> int:
    gates = [
        {"name": g.name, "passed": g.passed, "detail": g.detail, "status": g.status}
        for g in report.gates
    ]
    row = conn.execute(
        "INSERT INTO validation_report (experiment_id,run_id,passed,thresholds_status,n_trials,"
        "evidence,gates,created_at,refs) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING report_id",
        (exp_id, run_id, report.passed, report.thresholds_status, n_trials,
         Jsonb(vars(evidence)), Jsonb(gates), require_utc(now), Jsonb(dict(refs or {}))),
    ).fetchone()  # fmt: skip
    assert row is not None
    return int(row[0])


def validation_passed(conn: psycopg.Connection, run_id: int) -> bool:
    """True only for a passing report made against CONFIRMED (not provisional) thresholds."""
    row = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM validation_report WHERE run_id=%s AND passed"
        " AND thresholds_status='confirmed')",
        (run_id,),
    ).fetchone()
    assert row is not None
    return bool(row[0])
