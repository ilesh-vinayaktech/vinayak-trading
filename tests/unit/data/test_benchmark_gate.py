import json
from types import SimpleNamespace

from algo.data.benchmark_gate import blocker, is_enabled


def arts(eligible, blockers=()):
    found = {
        "series": "B1_X",
        "uses": {"BENCHMARK_GATE": {"eligible": eligible, "blockers": list(blockers)}},
    }
    return SimpleNamespace(version="1.4", eligibility_of=lambda i: found if i == 1 else None)


def test_the_gate_is_on_only_when_the_file_says_so(tmp_path):
    f = tmp_path / "g.json"
    assert not is_enabled(f)  # no file
    f.write_text(json.dumps({"enabled": False}))
    assert not is_enabled(f)
    f.write_text(json.dumps({"enabled": "yes"}))
    assert not is_enabled(f)  # not the boolean true
    f.write_text(json.dumps({"enabled": True}))
    assert is_enabled(f)


def test_off_lets_anything_through_on_needs_a_release_that_calls_the_benchmark_eligible():
    assert blocker(None, 1, enabled=False) is None
    assert "no benchmark release" in blocker(None, 1, enabled=True)
    assert "not in benchmark release 1.4" in blocker(arts(True), 2, enabled=True)
    assert blocker(arts(True), 1, enabled=True) is None
    why = blocker(arts(False, ["U06: x", "U08: y"]), 1, enabled=True)
    assert "not BENCHMARK_GATE_ELIGIBLE in release 1.4" in why and "U06: x; U08: y" in why
    assert "no reason recorded" in blocker(arts(False), 1, enabled=True)
