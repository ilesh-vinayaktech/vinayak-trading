# ruff: noqa: E501
"""Run only what your change touches (minutes, not 20): lint + types, then the tests that depend on
the changed Python modules (static import graph over src/algo and tests, transitive), then the
frontend tests related to changed frontend files. `make check` stays the full gate, 1-2 times a day:
this does NOT check coverage floors and cannot see dynamic imports.
usage: quick_check.py [--base HEAD | --files PATH...] [--workers 2] [--list]   (--list: show the plan, run nothing)"""

import argparse
import ast
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--base", default="HEAD", help="compare the working tree with this commit")
ap.add_argument(
    "--workers", type=int, default=2, help="pytest-xdist workers (each starts a test database)"
)
ap.add_argument(
    "--files", nargs="+", help="treat exactly these paths as the change instead of asking git"
)
ap.add_argument("--list", action="store_true")
a = ap.parse_args()


def git(*args: str) -> list[str]:
    out = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [line for line in out.splitlines() if line]


changed = sorted(
    a.files
    or set(git("diff", "--name-only", a.base)) | set(git("ls-files", "-o", "--exclude-standard"))
)
py_files = [p for p in (ROOT / "src" / "algo").rglob("*.py")] + [
    p for p in (ROOT / "tests").rglob("*.py")
]


def dotted(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts[0] == "src":
        parts = parts[1:]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


modules = {dotted(p): p for p in py_files}
imports: dict[str, set[str]] = defaultdict(set)  # module -> modules it imports
for name, path in modules.items():
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            targets = [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]
        else:
            continue
        imports[name] |= {t for t in targets if t in modules}
dependents: dict[str, set[str]] = defaultdict(set)
for name, deps in imports.items():
    for d in deps:
        dependents[d].add(name)

start = {
    dotted(ROOT / p)
    for p in changed
    if p.endswith(".py") and (ROOT / p).exists() and dotted(ROOT / p) in modules
}
affected, todo = set(start), list(start)
while todo:
    for dep in dependents[todo.pop()]:
        if dep not in affected:
            affected.add(dep)
            todo.append(dep)
tests = sorted(
    str(modules[m].relative_to(ROOT))
    for m in affected
    if modules[m].name.startswith("test_") and "tests" in modules[m].parts
)
notes = []
if (
    any(p.startswith("src/algo/data/store/migrations/") for p in changed)
    and (ROOT / "tests/integration/test_store.py").exists()
):
    tests.append("tests/integration/test_store.py")
if any(
    p.startswith("src/") and p not in git("ls-files") for p in changed
):  # a new module: its test must exist
    tests.append("tests/test_every_module_has_test.py")
if any(p in ("tests/conftest.py", "pyproject.toml") for p in changed):
    notes.append("conftest/pyproject changed: this selection is not enough, run `make check`")
tests = sorted(set(tests))
front = [
    p
    for p in changed
    if p.startswith("frontend/") and p.endswith((".ts", ".tsx")) and (ROOT / p).exists()
]

print(
    f"changed files: {len(changed)}; python modules touched: {len(start)}; dependents: {len(affected) - len(start)}"
)
print(f"tests selected: {len(tests)}; frontend files: {len(front)}")
for t in tests:
    print("  ", t)
for n in notes:
    print("NOTE:", n)
if a.list:
    sys.exit(0)


def run(*cmd: str, cwd: Path = ROOT) -> None:
    print("\n$", " ".join(cmd), flush=True)
    if subprocess.run(cmd, cwd=cwd).returncode:
        sys.exit(f"FAILED: {' '.join(cmd)}")


run("uv", "run", "ruff", "check", ".")
run("uv", "run", "ruff", "format", "--check", ".")
run("uv", "run", "mypy", "src")
if tests:
    workers = "0" if len(tests) == 1 else str(a.workers)
    run("uv", "run", "pytest", "-q", "-n", workers, "--no-cov", *tests)
if front:
    run("npx", "tsc", "--noEmit", cwd=ROOT / "frontend")
    run(
        "npx",
        "vitest",
        "related",
        "--run",
        *[p.removeprefix("frontend/") for p in front],
        cwd=ROOT / "frontend",
    )
print(
    "\nQUICK CHECK OK (not the full gate: no coverage floors, no dynamic imports; run `make check` before you call something done)"
)
