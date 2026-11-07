"""T0.12: every non-trivial module in src/algo must have a matching tests/**/test_<name>.py."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_module_has_a_test():
    tests = {p.name for p in (ROOT / "tests").rglob("test_*.py")}
    missing = [
        str(p.relative_to(ROOT))
        for p in (ROOT / "src/algo").rglob("*.py")
        if p.name != "__init__.py" and f"test_{p.name}" not in tests
    ]
    assert not missing, f"modules without tests: {missing}"
