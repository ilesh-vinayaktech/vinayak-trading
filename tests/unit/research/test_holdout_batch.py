from dataclasses import replace
from datetime import date

import pytest

from algo.research.holdout_batch import (
    EVALUATOR_VERSION,
    BatchError,
    Candidate,
    Capability,
    Manifest,
    Results,
    check_results,
    manifest_problems,
)
from algo.research.holdout_lock import Lock

LOCK = Lock(date(2024, 12, 31), date(2025, 1, 1), date(2026, 11, 13))


def cand(i, family="momentum", **over):
    base = dict(
        candidate_id=f"c{i}", family_id=family, strategy_version="1", parameter_hash=f"p{i}",
        dataset_sha256=f"d{i}", study_sha256=f"s{i}", validation_report_id=i,
    )  # fmt: skip
    return Candidate(**{**base, **over})


def manifest(**over):
    base = dict(
        batch_id=1, candidates=(cand(1), cand(2), cand(3, family="value")),
        family_trials={"momentum": 40, "value": 12}, date_from=LOCK.holdout_start, date_to=LOCK.holdout_end,
        correction_method="holm", correction_version="1", evaluator_version=EVALUATOR_VERSION,
    )  # fmt: skip
    return Manifest(**{**base, **over})


def test_a_complete_manifest_has_no_problems_and_a_stable_hash():
    m = manifest()
    assert manifest_problems(m, LOCK, 1) == []
    assert m.sha256 == manifest().sha256
    assert m.sha256 != manifest(correction_version="2").sha256
    assert (
        m.sha256
        != replace(
            m, candidates=(*m.candidates[:2], cand(3, family="value", parameter_hash="changed"))
        ).sha256
    )


@pytest.mark.parametrize(
    ("over", "text"),
    [
        ({"candidates": ()}, "no candidates"),
        ({"candidates": (cand(1), cand(1))}, "twice"),
        ({"candidates": (cand(1, dataset_sha256=""),)}, "dataset_sha256"),
        ({"candidates": (cand(1, family_id=""),)}, "family_id"),
        ({"date_from": date(2025, 1, 2)}, "must equal the global holdout"),
        ({"date_to": date(2026, 11, 12)}, "must equal the global holdout"),
        ({"evaluator_version": "other"}, "evaluator version"),
        ({"correction_method": ""}, "correction"),
        ({"family_trials": {"momentum": 40}}, "no trial count for family value"),
        ({"family_trials": {"momentum": 1, "value": 12}}, "fewer trials"),
        ({"batch_id": 2}, "another batch"),
    ],
)
def test_every_defect_in_a_manifest_is_named(over, text):
    problems = manifest_problems(manifest(**over), LOCK, 1)
    assert any(text in p for p in problems), problems


def test_the_evaluator_capability_cannot_be_forged_and_stops_working_when_revoked():
    sentinel = object()
    with pytest.raises(BatchError, match="only the evaluator"):
        Capability(object(), sentinel)
    from algo.research import holdout_batch

    cap = Capability(holdout_batch._TOKEN, sentinel)
    assert cap.reader is sentinel
    cap._revoke()
    with pytest.raises(BatchError, match="revoked"):
        _ = cap.reader


def test_results_must_cover_every_candidate_with_known_verdicts_only():
    m = manifest()
    good = Results(
        {
            ("c1", "oos_sharpe"): "PASS",
            ("c2", "oos_sharpe"): "FAIL",
            ("c3", "oos_sharpe"): "INSUFFICIENT_EVIDENCE",
        },
        {"x": 1},
    )
    check_results(m, good)  # no exception
    with pytest.raises(BatchError, match="no verdict for candidate c3"):
        check_results(m, Results({("c1", "g"): "PASS", ("c2", "g"): "PASS"}, {}))
    with pytest.raises(BatchError, match="not in the manifest"):
        check_results(m, Results({**good.verdicts, ("zz", "g"): "PASS"}, {}))
    with pytest.raises(BatchError, match="unknown verdict"):
        check_results(m, Results({**good.verdicts, ("c1", "g2"): "MAYBE"}, {}))
    with pytest.raises(BatchError, match="empty gate"):
        check_results(m, Results({**good.verdicts, ("c1", ""): "PASS"}, {}))
