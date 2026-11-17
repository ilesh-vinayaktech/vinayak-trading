"""The promotion path's reader of holdout verdicts (policy v3 section 5)."""

import pytest

from algo.promotion import verdicts
from algo.research.holdout_batch import BatchError


class Conn:
    def __init__(self, rows, later=()):
        self.rows, self.later, self.sql = rows, later, ""

    def execute(self, sql, params=None):
        self.sql = sql
        return self

    def fetchall(self):
        return self.later if "holdout_supplement" in self.sql else self.rows


def test_no_consumed_batch_means_no_verdicts_to_read():
    with pytest.raises(BatchError, match="no consumed"):
        verdicts.read_verdicts(Conn([]))


def test_verdicts_come_back_as_candidate_gate_verdict():
    assert verdicts.read_verdicts(Conn([("c1", "g", "PASS")])) == [("c1", "g", "PASS")]


def test_only_all_pass_with_at_least_one_pass_is_promotable():
    rows = [
        ("c1", "a", "PASS"),
        ("c1", "b", "NOT_APPLICABLE"),
        ("c2", "a", "PASS"),
        ("c2", "b", "INSUFFICIENT_EVIDENCE"),
        ("c3", "a", "FAIL"),
        ("c4", "a", "NOT_APPLICABLE"),
    ]
    c = Conn(rows)
    assert verdicts.promotable(c, "c1") is True
    assert verdicts.promotable(c, "c2") is False  # insufficient evidence is never a weak pass
    assert verdicts.promotable(c, "c3") is False
    assert verdicts.promotable(c, "c4") is False  # nothing passed
    assert verdicts.promotable(c, "nobody") is False


def test_supplements_come_back_as_candidate_gate_verdict():
    c = Conn([], later=[("c1", "g", "PASS")])
    assert verdicts.read_supplements(c) == [("c1", "g", "PASS")]
    with pytest.raises(BatchError):  # no consumed batch: nothing is promotable, supplement or not
        verdicts.promotable(Conn([]), "c1")


def test_a_no_evidence_check_counts_by_its_later_verdict_and_blocks_without_one():
    rows = [
        ("c1", "a", "PASS"),
        ("c1", "b", "INSUFFICIENT_EVIDENCE"),
        ("c2", "a", "PASS"),
        ("c2", "b", "INSUFFICIENT_EVIDENCE"),
    ]
    later = [("c1", "b", "PASS"), ("c2", "b", "FAIL")]
    c = Conn(rows, later)
    assert verdicts.promotable(c, "c1") is True  # completed later, passed
    assert verdicts.promotable(c, "c2") is False  # completed later, failed
    assert verdicts.promotable(Conn(rows), "c1") is False  # never completed: still blocks
