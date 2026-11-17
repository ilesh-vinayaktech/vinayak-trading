# ruff: noqa: E501
"""The only reader of holdout verdicts (docs/holdout-policy-v3.md section 5). It lives outside the research packages on purpose: no research, discovery, feature,
alpha-generation or strategy-generation code may import it (`tests/unit/test_holdout_access.py` fails if one does). Callers: the promotion path (`algo.paper.definitions`)."""

import psycopg

from algo.research.holdout_batch import BatchError


def read_verdicts(conn: psycopg.Connection) -> list[tuple[str, str, str]]:
    """The only thing research code may read of the evaluation: (candidate, gate, verdict), once the batch is CONSUMED."""
    rows = conn.execute(
        "SELECT v.candidate_id, v.gate, v.verdict FROM holdout_verdict v JOIN holdout_batch b USING (batch_id)"
        " WHERE b.state='CONSUMED' ORDER BY 1, 2"
    ).fetchall()
    if not rows:
        raise BatchError("no consumed holdout batch: there are no verdicts to read")
    return [(r[0], r[1], r[2]) for r in rows]


def promotable(conn: psycopg.Connection, candidate_id: str) -> bool:
    """Every verdict PASS or NOT_APPLICABLE and at least one PASS. Insufficient evidence is never a weak pass."""
    got = {v for c, _, v in read_verdicts(conn) if c == candidate_id}
    return bool(got) and got <= {"PASS", "NOT_APPLICABLE"} and "PASS" in got


def read_supplements(conn: psycopg.Connection) -> list[tuple[str, str, str]]:
    """(candidate, gate, verdict) of checks that had no evidence and were completed later. Information for the owner: nothing here makes a strategy promotable."""
    return [
        (r[0], r[1], r[2])
        for r in conn.execute(
            "SELECT candidate_id, gate, verdict FROM holdout_supplement ORDER BY 1, 2"
        ).fetchall()
    ]
