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


def test_session_dependencies_are_per_series_and_keep_existence_kind_and_hours_apart(tmp_path):
    release(tmp_path, "1.0", tmp_path / "benchmark-audit")
    a = artifacts.load(tmp_path)
    dep = a.session_dependencies(1)
    assert dep["series"] == "B1_X_GROSS_TRI"
    assert [(r["code"], r["count"]) for r in dep["observed"]] == [("CONFIRMED_REGULAR", 2)]
    assert (
        dep["observed"][0]["existence"] == "CONFIRMED"
        and dep["observed"][0]["hours"] == "ASSUMED_CURRENT_SCHEDULE"
    )
    assert [(r["code"], r["count"]) for r in dep["missing"]] == [("EXPECTED_CLOSED", 4)]
    assert dep["missing"][0]["existence"] is None
    assert a.session_dependencies(9) is None


def test_a_confirmed_special_session_is_described_as_existence_only():
    (row,) = artifacts.describe_outcomes({"CONFIRMED_SPECIAL": 32})
    assert row["label"] == "session existence confirmed by an exchange file; kind not confirmed"
    assert (row["existence"], row["kind"], row["hours"]) == ("CONFIRMED", "UNCONFIRMED", "UNKNOWN")
    assert "special" not in row["label"].replace("kind", "")  # the label never asserts a kind


def test_every_observed_and_missing_outcome_has_a_description_and_unknown_codes_fall_back():
    rows = artifacts.describe_outcomes(
        {
            **dict.fromkeys(artifacts.OBSERVED, 1),
            **dict.fromkeys(artifacts.MISSING, 2),
            "SOMETHING_NEW": 3,
        }
    )
    assert len(rows) == len(artifacts.OBSERVED) + len(artifacts.MISSING) + 1
    assert next(r for r in rows if r["code"] == "SOMETHING_NEW")["label"] == "something new"
    assert all(r["existence"] for r in rows if r["code"] in artifacts.OBSERVED)
    assert [r["code"] for r in rows] == sorted(r["code"] for r in rows)


def test_session_properties_are_only_reported_for_the_file_the_release_froze(tmp_path):
    import hashlib

    f = tmp_path / "sessions.json"
    f.write_text(
        json.dumps(
            {
                "sessions": [
                    {"kind_status": "UNCONFIRMED (a)", "hours_status": "UNKNOWN (b)"},
                    {"kind_status": "UNCONFIRMED (a)", "hours_status": "UNKNOWN (b)"},
                    {"kind_status": "CONFIRMED (c)", "hours_status": "VERIFIED (d)"},
                ]
            }
        )
    )
    frozen = {
        "calendar_inputs": {"sessions_file_sha256": hashlib.sha256(f.read_bytes()).hexdigest()}
    }
    props = artifacts.session_properties(f, frozen)
    assert props == {
        "listed_sessions": 3,
        "kind": {"CONFIRMED": 1, "UNCONFIRMED": 2},
        "opening_time": {"UNKNOWN": 2, "VERIFIED": 1},
        "closing_time": {"UNKNOWN": 2, "VERIFIED": 1},
    }
    assert (
        artifacts.session_properties(f, {"calendar_inputs": {"sessions_file_sha256": "other"}})
        is None
    )
    assert artifacts.session_properties(f, {}) is None
    assert artifacts.session_properties(tmp_path / "missing.json", frozen) is None
