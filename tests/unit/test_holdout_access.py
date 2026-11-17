"""Holdout policy v3 section 5: research code can never read holdout verdicts. The reader lives in `algo.promotion`; no research-side package may import it
(or the promotion-path modules that call it), directly or inside a function."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "algo"
RESEARCH = (
    "research",
    "alpha",
    "features",
    "factory",
    "strategies",
    "strategy",
    "screener",
    "learning",
    "indicators",
    "backtest",
    "data",
)
FORBIDDEN = ("algo.promotion", "algo.paper.definitions")
# the evaluator and batch code write verdicts but are the policy's own; they still must not READ them
ALLOWED_RESEARCH_IMPORTERS: set[str] = set()


def imports(path: Path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            yield from (a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
            yield from (f"{node.module}.{a.name}" for a in node.names)


def test_no_research_module_imports_the_verdict_reader():
    bad = []
    for pkg in RESEARCH:
        for f in (SRC / pkg).rglob("*.py"):
            rel = str(f.relative_to(SRC))
            if rel in ALLOWED_RESEARCH_IMPORTERS:
                continue
            bad += [f"{rel} imports {m}" for m in imports(f) if m.startswith(FORBIDDEN)]
    assert bad == []


def test_the_reader_is_not_left_in_the_research_package():
    text = (SRC / "research" / "holdout_batch.py").read_text()
    assert "def read_verdicts" not in text and "def promotable" not in text


def test_the_check_would_catch_an_offender(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("def g():\n    from algo.promotion import verdicts\n")
    assert any(m.startswith(FORBIDDEN) for m in imports(f))
