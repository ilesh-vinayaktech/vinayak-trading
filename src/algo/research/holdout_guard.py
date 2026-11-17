# ruff: noqa: E501
"""Holdout policy v3 section 7: the evaluator is given a guarded handle, never a database connection.

`GuardedConnection` exists only after the first-read marker is committed (the batch module is the only place that makes one) and answers `execute` for queries over an allow-list of
tables: SOURCE inputs (bars, corporate actions, instrument master and identity, universe lists, calendar, cost schedules, index levels, point-in-time filings) and the development-side
metadata the evaluator needs to rebuild a candidate (its study and development report). It has no other method: no cursor, no commit, no transaction. A query naming any other table
(derived signals, paper runs, features, stored backtests, scorecards, holdout verdicts) is refused with an error, not quietly answered.
Limit, stated plainly (policy section 7): this is a table allow-list in the application, not a database role. It does not itself limit WHICH DATES a query returns (the window plus the
candidate's warm-up) or serve each decision only what was known then (`as_of`): those stay the job of the point-in-time readers the evaluator uses, and are checked by their own tests."""

from __future__ import annotations

import re
from typing import Any

import psycopg

SOURCE_TABLES = frozenset(
    {
        # prices, corporate actions and their review decisions
        "bar_1d", "bar_1m", "corporate_action", "corporate_action_relationship", "corporate_action_upcoming", "action_resolution", "review_decision", "security_conversion",
        # instrument master, identity, terms, sectors, exchanges and the trading calendar
        "instrument", "instrument_alias", "instrument_terms", "instrument_sector", "exchange", "market_session",
        # the universe inputs: AMFI lists and index membership with their release documents
        "market_cap_list", "market_cap_rank", "index_membership_event", "index_membership_coverage", "index_monthly_constituent", "index_monthly_snapshot", "index_snapshot",
        "index_release_document", "index_release_row", "index_release_override", "index_release_revocation", "index_placeholder_replacement",
        # cost schedules, index levels, point-in-time filings, and the identity of the frozen source snapshot
        "cost_schedule", "benchmark", "benchmark_observation", "benchmark_validation", "fundamental_fact", "fundamental_filing", "fundamental_unloaded",
        "data_freeze", "data_freeze_item", "data_snapshot", "snapshot_partition", "partition_load", "regulatory_config",
    }
)  # fmt: skip
STUDY_METADATA_TABLES = frozenset(
    {"experiment", "validation_report", "study_dataset", "research_family", "research_lock"}
)
ALLOWED = SOURCE_TABLES | STUDY_METADATA_TABLES

_TABLE = re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE)\s+(?!LATERAL\b)([a-zA-Z_][\w.]*)", re.IGNORECASE)
_CTE = re.compile(r"(?:\bWITH|,)\s*(?:RECURSIVE\s+)?([a-zA-Z_]\w*)\s+AS\s*\(", re.IGNORECASE)
_WRITE = re.compile(r"^\s*(INSERT|UPDATE|DELETE|TRUNCATE|ALTER|DROP|CREATE)\b", re.IGNORECASE)
_TOKEN = object()


class GuardError(Exception):
    pass


def tables_of(sql: str) -> set[str]:
    """The relation names a query reads or writes (CTE names excluded)."""
    ctes = {m.lower() for m in _CTE.findall(sql)}
    return {t.lower().split(".")[-1] for t in _TABLE.findall(sql)} - ctes


class GuardedConnection:
    __slots__ = ("_conn", "log")

    def __init__(self, token: object, conn: psycopg.Connection) -> None:
        if token is not _TOKEN:
            raise GuardError("only the batch module can create a guarded connection")
        self._conn = conn
        self.log: list[str] = []

    def execute(self, query: str, params: Any = None, **kw: Any) -> Any:
        sql = query if isinstance(query, str) else str(query)
        if _WRITE.match(sql):
            raise GuardError("the evaluator reads; it never writes")
        bad = sorted(t for t in tables_of(sql) if t not in ALLOWED)
        if bad:
            raise GuardError(
                f"the evaluator may not read {', '.join(bad)}: only source inputs and the study's own record are reachable"
            )
        self.log.append(sql)
        return self._conn.execute(sql, params, **kw)


def guard(conn: psycopg.Connection) -> GuardedConnection:
    """Used by `holdout_batch.evaluate` after the first-read marker is durable, and nowhere else."""
    return GuardedConnection(_TOKEN, conn)
