"""Thin research-run orchestration: label, gate and fingerprint one engine run.

It coordinates; it never re-implements the engine, ledger, costs or statistics. Only
ENGINEERING_TEST_ONLY runs exist today. They touch no validation registry and count as no trial.
Registered and exploratory runs are refused until strict readiness passes and an experiment is
registered (`scripts/stage4_readiness.py`)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import psycopg

from algo.backtest.engine import BacktestConfig, RunResult, run_backtest
from algo.strategy.base import Strategy


class Purpose(StrEnum):
    ENGINEERING_TEST_ONLY = "ENGINEERING_TEST_ONLY"
    EXPLORATORY_RESEARCH = "EXPLORATORY_RESEARCH"
    REGISTERED_EXPERIMENT = "REGISTERED_EXPERIMENT"


@dataclass(frozen=True)
class Execution:
    result: RunResult
    manifest: dict[str, Any]


def _fingerprint(versions: dict[int, str]) -> str:
    body = json.dumps(sorted(versions.items()), separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


def manifest(r: RunResult, purpose: Purpose) -> dict[str, Any]:
    """Everything needed to reproduce and audit the run, deterministic for identical inputs."""
    return {
        "purpose": purpose.value,
        "strategy": {"id": r.strategy_id, "version": r.strategy_version,
                     "params_hash": r.params_hash},
        "code_version": r.code_version,
        "window": [str(r.config.start), str(r.config.end)],
        "mode": r.config.mode.value,
        "cost": r.config.cost.describe(),
        "dataset_fingerprint": _fingerprint(r.adjustment_versions),
        "result_hash": r.result_hash,
    }  # fmt: skip


def execute(
    conn: psycopg.Connection, strategy: Strategy, cfg: BacktestConfig, *, purpose: Purpose,
    code_version: str = "unversioned",
) -> Execution:  # fmt: skip
    if purpose is not Purpose.ENGINEERING_TEST_ONLY:
        raise NotImplementedError(
            f"{purpose.value} runs need strict readiness and a registered experiment first"
        )
    result = run_backtest(conn, strategy, cfg, code_version=code_version)
    return Execution(result, manifest(result, purpose))
