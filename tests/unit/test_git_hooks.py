import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_the_pre_commit_hook_runs_the_secret_scan_and_ruff_and_is_executable():
    hook = ROOT / ".githooks/pre-commit"
    text = hook.read_text()
    assert os.access(hook, os.X_OK) and "scripts/scan_secrets.py" in text and "ruff check" in text
    assert (ROOT / "scripts/install_hooks.sh").exists() and os.access(
        ROOT / "scripts/install_hooks.sh", os.X_OK
    )


def test_the_hook_fails_a_commit_that_stages_a_seeded_secret(tmp_path):
    """A throwaway repo with the real hook: staging a key-shaped string must make the hook exit non-zero."""
    run = lambda *a, **k: subprocess.run(a, cwd=tmp_path, capture_output=True, text=True, **k)  # noqa: E731
    run("git", "init", "-q")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/scan_secrets.py").write_text(
        (ROOT / "scripts/scan_secrets.py").read_text()
    )
    (tmp_path / "leak.txt").write_text("k = '" + "AKIA" + "IOSFODNN7EXAMPLE" + "'\n")
    run("git", "add", "-A")
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    r = subprocess.run(
        ["sh", str(ROOT / ".githooks/pre-commit")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode != 0 and "leak.txt:1: aws access key" in r.stdout
