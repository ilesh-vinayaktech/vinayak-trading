"""T0.7: nothing under src/ reads the system clock except the Clock implementation: time comes from an injected Clock."""

import ast
from pathlib import Path

SRC = Path(__file__).parents[2] / "src"
ALLOWED = {"algo/core/clock.py"}  # the one place that wraps the system clock
CLOCK_CALLS = {
    ("datetime", "now"), ("datetime", "utcnow"), ("datetime", "today"), ("date", "today"), ("time", "time"), ("time", "time_ns"),
}  # fmt: skip


def offenders(source: str) -> list[int]:
    return [
        n.lineno
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name)
        and (n.func.value.id, n.func.attr) in CLOCK_CALLS
    ]


def test_no_module_under_src_reads_the_system_clock_except_the_clock_itself():
    bad = {}
    for p in SRC.rglob("*.py"):
        rel = p.relative_to(SRC).as_posix()
        if rel not in ALLOWED and (lines := offenders(p.read_text())):
            bad[rel] = lines
    assert bad == {}, f"inject a Clock instead of reading the system clock: {bad}"


def test_the_detector_sees_each_kind_of_call():
    for call in (
        "datetime.now()",
        "datetime.utcnow()",
        "date.today()",
        "time.time()",
    ):
        assert offenders(f"x = {call}\n") == [1], call
    assert offenders("x = clock.now()\ny = datetime.fromisoformat('2026-01-01')\n") == []
