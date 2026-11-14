# ruff: noqa: E501
"""Run only what your change touches (minutes, not 20): lint + types, then the tests that EXECUTE the
changed source files, then the frontend tests related to changed frontend files.
Which tests execute which file comes from the last full run (`make cov` records a coverage context per
test in .coverage); without that map, or for a file the map has never seen, it falls back to a static
import graph (transitive, much broader). `make check` stays the full gate, 1-2 times a day:
this does NOT check coverage floors and cannot see dynamic imports.
usage: quick_check.py [--base HEAD | --files PATH...] [--workers 16] [--list]   (--list: show the plan, run nothing)"""

import argparse
import ast
import sqlite3
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--base", default="HEAD", help="compare the working tree with this commit")
ap.add_argument(
    "--workers", type=int, default=16, help="pytest-xdist workers (each starts a test database)"
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


def mapped_tests() -> tuple[set[str], set[str], str]:
    """(tests that executed any changed src file, changed src files the map has never seen, note)."""
    db = ROOT / ".coverage"
    src = [
        p
        for p in changed
        if p.startswith("src/algo/") and p.endswith(".py") and (ROOT / p).exists()
    ]
    if not src:
        return set(), set(), ""
    if not db.exists():
        return (
            set(),
            set(src),
            "no .coverage map: run `make check` once (it records which test runs which file)",
        )
    con = sqlite3.connect(db)
    try:
        if not con.execute("SELECT count(*) FROM context WHERE context != ''").fetchone()[0]:
            return (
                set(),
                set(src),
                "the last coverage run had no per-test contexts: run `make check` once",
            )
        table = (
            "arc"
            if con.execute("SELECT 1 FROM sqlite_master WHERE name='arc'").fetchone()
            else "line_bits"
        )
        found: set[str] = set()
        unseen: set[str] = set()
        for p in src:
            rows = con.execute(
                f"SELECT DISTINCT c.context FROM {table} t JOIN file f ON f.id = t.file_id"
                " JOIN context c ON c.id = t.context_id WHERE f.path LIKE ? AND c.context != ''",
                (f"%/{p}" if not p.startswith("/") else p,),
            ).fetchall()
            if (
                not rows
                and not con.execute("SELECT 1 FROM file WHERE path LIKE ?", (f"%/{p}",)).fetchone()
            ):
                unseen.add(p)  # a file the recorded run never imported (new since then)
            found |= {r[0].split("::")[0] for r in rows}
        age = (time.time() - db.stat().st_mtime) / 3600
        return found, unseen, f"map from the coverage run {age:.0f} h ago"
    finally:
        con.close()


mapped, unseen, map_note = mapped_tests()
fallback = {dotted(ROOT / p) for p in unseen} if map_note.startswith("map from") else start
affected, todo = set(fallback), list(fallback)
while todo:
    for dep in dependents[todo.pop()]:
        if dep not in affected:
            affected.add(dep)
            todo.append(dep)
tests = sorted(
    {
        str(modules[m].relative_to(ROOT))
        for m in affected
        if modules[m].name.startswith("test_") and "tests" in modules[m].parts
    }
    | mapped
    | {
        p
        for p in changed
        if p.startswith("tests/") and Path(p).name.startswith("test_") and (ROOT / p).exists()
    }
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
print(
    f"tests selected: {len(tests)}; frontend files: {len(front)}"
    + (f"; {map_note}" if map_note else "")
)
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
