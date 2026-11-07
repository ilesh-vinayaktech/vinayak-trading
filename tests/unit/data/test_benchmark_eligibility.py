from algo.data.benchmark_eligibility import DAILY, GATE, INTRADAY, assess
from algo.data.benchmark_validate import REPORT_VERSION

GOOD = {"covers_current_dataset": True, "report_version": REPORT_VERSION,
        "technical_validation_passed": True, "check_states": {"a": "PASS"},
        "factsheet_all_passed": True}  # fmt: skip


def f(id_, status="UNRESOLVED", applies=("ALL",), blocks=()):
    return {"id": id_, "title": f"t{id_}", "status": status, "applies_to": list(applies),
            "blocks": list(blocks)}  # fmt: skip


def test_a_current_validation_with_no_findings_is_gate_eligible_only_on_paper():
    r = assess("B1", GOOD, [])
    assert r["state"] == "BENCHMARK_GATE_ELIGIBLE"
    assert all(r["uses"][u]["eligible"] for u in (DAILY, INTRADAY, GATE))


def test_any_unresolved_finding_blocks_the_gate_but_only_named_uses_block_research():
    r = assess("B1", GOOD, [f("U1", blocks=[INTRADAY]), f("U2")])
    assert r["state"] == "RESEARCH_ELIGIBLE" and r["uses"][DAILY]["eligible"]
    assert not r["uses"][INTRADAY]["eligible"] and r["uses"][INTRADAY]["blockers"] == ["U1: tU1"]
    assert r["uses"][GATE]["blockers"] == ["U1: tU1", "U2: tU2"]
    assert r["applicable_findings"] == ["U1", "U2"]


def test_a_finding_that_blocks_daily_research_blocks_intraday_too():
    r = assess("B1", GOOD, [f("U1", blocks=[DAILY])])
    assert r["state"] == "DATA_INGESTED" and r["uses"][INTRADAY]["blockers"] == ["U1: tU1"]


def test_findings_apply_only_to_the_benchmarks_they_name_and_accepted_ones_do_not_block():
    fs = [f("U1", applies=["B2"], blocks=[DAILY]), f("U2", status="ACCEPTED_WITH_EVIDENCE")]
    r = assess("B1", GOOD, fs)
    assert r["applicable_findings"] == ["U2"] and r["state"] == "BENCHMARK_GATE_ELIGIBLE"
    assert assess("B2", GOOD, fs)["uses"][DAILY]["eligible"] is False


def test_a_stale_old_or_unreconciled_validation_blocks_everything():
    stale = {
        **GOOD,
        "covers_current_dataset": False,
        "report_version": "legacy",
        "factsheet_all_passed": False,
    }
    r = assess("B1", stale, [])
    assert r["state"] == "DATA_INGESTED" and len(r["uses"][DAILY]["blockers"]) == 3
    assert not r["uses"][GATE]["eligible"]


def test_an_accepted_exception_is_not_a_technical_pass_so_it_cannot_reach_the_gate():
    v = {**GOOD, "technical_validation_passed": False,
         "check_states": {"a": "PASS", "b": "ACCEPTED_WITH_EVIDENCE", "c": "UNRESOLVED"}}  # fmt: skip
    r = assess("B3", v, [])
    assert r["uses"][DAILY]["eligible"] and r["state"] == "RESEARCH_ELIGIBLE"
    assert r["uses"][GATE]["blockers"] == [
        "technical validation did not pass (an accepted exception is not a pass)"
    ]
    assert r["disclosed_check_findings"] == {"b": "ACCEPTED_WITH_EVIDENCE", "c": "UNRESOLVED"}
    failed = assess("B3", {**v, "check_states": {"a": "FAIL"}}, [])
    assert not failed["uses"][DAILY]["eligible"]
    assert failed["uses"][DAILY]["blockers"] == [
        "a check failed without an accepted or unresolved finding"
    ]
    none = assess("B3", {**v, "check_states": None}, [])
    assert none["disclosed_check_findings"] == {}
