# ruff: noqa: E501
"""Paper trading of a generated strategy definition, allowed only after its study passed the one global holdout.

Callers: algo.api.paper_routes (list and start) and tests/integration/paper/test_definitions.py. Nothing similar exists: algo.paper.configs copies a saved
strategy onto an account; a definition is not a saved strategy, it is locked inside its study, so the account takes a copy of the locked definition and
the settings the passed verdict chose. User's instruction: "keep the order": global holdout first, paper trading after it.

The gate is `verdicts.promotable("study-<experiment id>")`: the batch is CONSUMED and every verdict of that candidate is PASS or NOT_APPLICABLE with at least one PASS."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from algo.paper.book import PaperError
from algo.promotion import verdicts
from algo.research.holdout_batch import BatchError


def _batch_done(conn: psycopg.Connection) -> bool:
    try:
        verdicts.read_verdicts(conn)
    except BatchError:
        return False
    return True


def candidates(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Every definition study with a passed development verdict: what it is and where it stands on the way to paper trading."""
    rows = conn.execute(
        "SELECT DISTINCT ON (e.experiment_id) e.experiment_id, e.study->'spec', r.refs->'chosen'"
        " FROM experiment e JOIN validation_report r USING (experiment_id)"
        " WHERE e.strategy_id='dsl' AND r.passed ORDER BY e.experiment_id, r.report_id DESC"
    ).fetchall()
    done = _batch_done(conn)
    out = []
    for exp, spec, chosen in rows:
        defn = (spec or {}).get("definition")
        if not defn or chosen is None:
            continue
        ok = done and verdicts.promotable(conn, f"study-{exp}")
        out.append(
            {
                "experiment_id": exp, "strategy_id": defn["strategy_id"], "version": defn["version"], "name": spec["name"],
                "state": "ready" if ok else "failed_holdout" if done else "awaiting_holdout",
            }
        )  # fmt: skip
    return out


def start(conn: psycopg.Connection, user_id: UUID, experiment_id: int) -> str:
    """Put the account on this study's definition and chosen settings; returns its name. Refused unless the study passed the global holdout."""
    found = [c for c in candidates(conn) if c["experiment_id"] == experiment_id]
    if not found:
        raise PaperError("no such definition study with a passed verdict")
    if found[0]["state"] != "ready":
        raise PaperError(
            "this strategy has not passed the global holdout (2025 onward): paper trading starts only after it has"
        )
    row = conn.execute(
        "SELECT e.study->'spec', r.refs->'chosen' FROM experiment e JOIN validation_report r USING (experiment_id)"
        " WHERE e.experiment_id=%s AND r.passed ORDER BY r.report_id DESC LIMIT 1",
        (experiment_id,),
    ).fetchone()
    assert row is not None
    spec, chosen = row
    held = {
        "definition": spec["definition"], "universe": spec["universe"], "experiment_id": experiment_id, "name": spec["name"],
    }  # fmt: skip
    done = conn.execute(
        "UPDATE paper_account SET strategy_id='dsl', universe='segments', max_instruments=NULL, timeframe='1D', params=%s, screen=NULL, definition=%s, config_id=NULL WHERE user_id=%s",
        (Jsonb(chosen), Jsonb(held), user_id),
    )
    if done.rowcount == 0:
        raise PaperError("no paper account yet")
    return str(spec["name"])
