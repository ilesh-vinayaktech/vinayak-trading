import json

import pytest

from algo.api import artifacts


def write(p, doc):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc))


def release(docs, version, audit_dir):
    write(docs / f"benchmark-release-{version}" / "release.json", {"release": version})
    write(audit_dir / "benchmark_eligibility.json", {
        "benchmarks": {"B1_X_GROSS_TRI": {"state": "RESEARCH_ELIGIBLE", "uses": {}}},
        "instrument_level_blocked_dates": []})  # fmt: skip
    write(audit_dir / "benchmark_unresolved_findings.json", {"findings": [
        {"id": "U1", "applies_to": ["ALL"]}, {"id": "U2", "applies_to": ["B1"]},
        {"id": "U3", "applies_to": ["B2"]}]})  # fmt: skip
    write(audit_dir / "benchmark_alignment_report.json", {"benchmarks": {}})
    write(audit_dir / "session_reconciliation_report.json", {
        "observed_counts": {},
        "observed": {"2024-01-01": ["CONFIRMED_REGULAR", ["B1", "B2"]], "2024-01-02": ["X", ["B2"]],
                     "2024-01-03": ["CONFIRMED_REGULAR", ["B1"]]},
        "missing_counts": {"B1_X_GROSS_TRI": {"EXPECTED_CLOSED": 4}}})  # fmt: skip


def test_the_newest_release_is_used_and_its_matching_audit_directory_is_read(tmp_path):
    release(tmp_path, "1.0", tmp_path / "benchmark-audit")
    release(tmp_path, "1.1", tmp_path / "benchmark-audit-1.1")
    write(tmp_path / "benchmark-release-1.10" / "ignored" / "x.json", {})  # no release.json
    a = artifacts.load(tmp_path)
    assert a is not None and a.version == "1.1"
    assert artifacts.latest_release_dir(tmp_path).name == "benchmark-release-1.1"
    assert artifacts.audit_dir_for(tmp_path, "1.0").name == "benchmark-audit"
    assert artifacts.audit_dir_for(tmp_path, "1.1").name == "benchmark-audit-1.1"


def test_1_10_sorts_after_1_9(tmp_path):
    for v in ("1.9", "1.10"):
        write(tmp_path / f"benchmark-release-{v}" / "release.json", {"release": v})
    assert artifacts.latest_release_dir(tmp_path).name == "benchmark-release-1.10"


def test_no_release_means_no_artifacts(tmp_path):
    assert artifacts.load(tmp_path) is None
    assert artifacts.latest_release_dir(tmp_path) is None


def test_series_eligibility_and_findings_are_looked_up_by_benchmark_id(tmp_path):
    release(tmp_path, "1.0", tmp_path / "benchmark-audit")
    a = artifacts.load(tmp_path)
    assert a.series_for(1) == "B1_X_GROSS_TRI" and a.series_for(9) is None
    assert a.eligibility_of(1)["state"] == "RESEARCH_ELIGIBLE" and a.eligibility_of(9) is None
    assert [f["id"] for f in a.findings_for(1)] == ["U1", "U2"]
    assert a.findings_for(9) == []


@pytest.mark.parametrize("name", ["not-a-series"])
def test_a_series_name_without_a_benchmark_prefix_is_never_matched(tmp_path, name):
    release(tmp_path, "1.0", tmp_path / "benchmark-audit")
    a = artifacts.load(tmp_path)
    object.__setattr__(a, "eligibility", {"benchmarks": {name: {}}})
    assert a.series_for(1) is None


def test_session_dependencies_are_per_series(tmp_path):
    release(tmp_path, "1.0", tmp_path / "benchmark-audit")
    a = artifacts.load(tmp_path)
    assert a.session_dependencies(1) == {
        "series": "B1_X_GROSS_TRI", "observed_outcomes": {"CONFIRMED_REGULAR": 2},
        "missing_outcomes": {"EXPECTED_CLOSED": 4}}  # fmt: skip
    assert a.session_dependencies(9) is None
