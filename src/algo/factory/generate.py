# ruff: noqa: E501
"""Strategy definitions from alpha candidates (plan.md section 7): a CANDIDATE hypothesis becomes a registered, immutable strategy definition built from FIXED PRIORS only.

Callers: tests/unit/factory/test_generate.py, tests/integration/factory/test_generate.py and the factory scripts. Reads alpha_hypothesis (migration 078), writes strategy_definition through
algo.factory.registry (insert-only). User's instruction: "can't we start Strategy definitions: nothing yet turns a candidate into a written strategy rule."

The rule is the plainest one the evidence supports, and nothing in it is fitted to the development data:
  * A feature with a POSITIVE rank IC (higher value, higher later return): hold the strongest ENTRY_SHARE% of stocks each day by that feature, sell when a held stock falls into the weakest
    EXIT_SHARE%. A NEGATIVE IC mirrors it (hold the weakest, sell into the strongest). The shares are round priors chosen before any result, not tuned thresholds: the language compares a stock
    with the others that day (TOP_PERCENT / BOTTOM_PERCENT), so no cut-off value ever comes from the data.
  * MAX_POSITIONS equal-weight positions, each capped at MAX_POSITION_PERCENT; the rebalance follows the horizon the signal was measured at (a one-day signal daily, up to a week weekly,
    longer monthly), because trading faster than the signal lasts only pays costs.
  * A candidate the language cannot express (a feature whose value depends on all history, one that reads filings, no direction) is REFUSED WITH THE REASON, never approximated.
  * One definition per feature and horizon: a later batch that finds the same idea again does not make a second strategy. Nothing here validates, promotes or trades anything: a generated
    definition is only a hypothesis written down, and it still has to pass experiments, validation and the holdout like any other."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg

from algo.factory import registry
from algo.factory.dsl import CHAINED, FILINGS_FEATURES, StrategyDef
from algo.features import registry as feature_registry

ENTRY_SHARE = 20  # hold the strongest (or weakest) fifth
EXIT_SHARE = 50  # sell when the stock is in the wrong half
MAX_POSITIONS = 20
MAX_POSITION_PERCENT = 10


class NotExpressible(Exception):
    pass


class GenerateError(Exception):
    pass


@dataclass(frozen=True)
class Hypothesis:
    hypothesis_id: int
    batch: int
    feature: str
    version: str
    horizon: int
    direction: str | None
    mean_ic: float | None
    p_adjusted: float | None


@dataclass(frozen=True)
class Created:
    strategy_id: str
    hypothesis_id: int


@dataclass(frozen=True)
class Refused:
    hypothesis_id: int
    feature: str
    horizon: int
    reason: str


@dataclass
class Report:
    created: list[Created] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)
    refused: list[Refused] = field(default_factory=list)


def _cadence(horizon: int) -> str:
    return "DAILY" if horizon <= 1 else "WEEKLY" if horizon <= 5 else "MONTHLY"


def definition_for(h: Hypothesis) -> StrategyDef:
    if h.feature not in feature_registry.DEFINITIONS:
        raise NotExpressible(f"{h.feature} is not a feature in the registry: it is not a feature")
    if h.feature in CHAINED:
        raise NotExpressible(
            f"{h.feature} depends on all of its history, not a window, so a strategy definition cannot use it yet"
        )
    if h.feature in FILINGS_FEATURES:
        raise NotExpressible(
            f"{h.feature} reads a company's filings, which the strategy interpreter does not have yet"
        )
    if h.direction not in ("POSITIVE", "NEGATIVE"):
        raise NotExpressible(
            "the result has no direction (a rank IC of zero or none): there is nothing to hold"
        )
    up = h.direction == "POSITIVE"
    strong, weak = ("TOP_PERCENT", "BOTTOM_PERCENT") if up else ("BOTTOM_PERCENT", "TOP_PERCENT")
    cadence = _cadence(h.horizon)
    ic = "n/a" if h.mean_ic is None else f"{h.mean_ic:.4f}"
    p = "n/a" if h.p_adjusted is None else f"{h.p_adjusted:.4f}"
    return StrategyDef.model_validate(
        {
            "strategy_id": f"ALPHA_{h.feature.upper()}_H{h.horizon}",
            "version": 1,
            "description": (
                f"Hold the {ENTRY_SHARE}% of stocks with the {'highest' if up else 'lowest'} {h.feature} each {cadence.lower()} period; sell when a stock falls into the {EXIT_SHARE}% on the wrong side. "
                f"Generated from alpha hypothesis {h.hypothesis_id} (batch {h.batch}): mean rank IC {ic}, corrected p {p}, measured {h.horizon} days ahead. A written-down hypothesis, not a validated strategy."
            ),
            "universe": "MEMBERS",
            "timeframe": "DAILY",
            "entry": {"all": [{"feature": h.feature, "op": strong, "value": ENTRY_SHARE}]},
            "exit": {"any": [{"feature": h.feature, "op": weak, "value": EXIT_SHARE}]},
            "ranking": {"feature": h.feature, "order": "DESC" if up else "ASC"},
            "position": {"max_positions": MAX_POSITIONS, "sizing": "EQUAL_WEIGHT"},
            "risk": {"max_position_percent": MAX_POSITION_PERCENT},
            "rebalance": cadence,
        }
    )


def candidates(conn: psycopg.Connection) -> list[Hypothesis]:
    rows = conn.execute(
        "SELECT hypothesis_id, batch_id, feature_name, feature_version, horizon_days, evidence FROM alpha_hypothesis WHERE research_status = 'CANDIDATE' ORDER BY hypothesis_id"
    ).fetchall()
    out = []
    for hid, batch, name, version, horizon, ev in rows:
        e: dict[str, Any] = ev
        out.append(
            Hypothesis(
                hid,
                batch,
                name,
                version,
                horizon,
                e.get("direction"),
                e.get("mean_ic"),
                e.get("p_adjusted"),
            )
        )
    return out


def generate_from_candidates(conn: psycopg.Connection, *, by: str, now: datetime) -> Report:
    """One registered definition per feature and horizon among the CANDIDATE hypotheses; what exists is left alone, what cannot be written is reported with its reason."""
    if not by.strip():
        raise GenerateError("a generated definition needs who ran it")
    report = Report()
    for h in candidates(conn):
        try:
            defn = definition_for(h)
        except NotExpressible as e:
            report.refused.append(Refused(h.hypothesis_id, h.feature, h.horizon, str(e)))
            continue
        if registry.versions(conn, defn.strategy_id):
            if defn.strategy_id not in report.existing:
                report.existing.append(defn.strategy_id)
            continue
        registry.register(
            conn,
            defn,
            by=by,
            reason=f"generated from alpha hypothesis {h.hypothesis_id} (CANDIDATE in batch {h.batch}): {h.feature} at {h.horizon} days, mean rank IC {h.mean_ic}",
            now=now,
        )
        report.created.append(Created(defn.strategy_id, h.hypothesis_id))
    return report
