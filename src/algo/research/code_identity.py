# ruff: noqa: E501
"""Which code produced a result: the git commit, whether the source differs from it, and the hash of a strategy's own file."""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]


def git_state(run: Callable[..., Any] = subprocess.run) -> tuple[str, bool]:
    """(commit, dirty). Dirty means a tracked or new file under src/ or config/ differs from the commit. Without a usable git the
    commit is "unknown" and the state counts as dirty: a result nobody can reproduce must not look reproducible."""
    try:
        head = run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
        )
        status = run(
            ["git", "status", "--porcelain", "--", "src", "config"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "unknown", True
    if head.returncode != 0 or status.returncode != 0:
        return "unknown", True
    return head.stdout.strip(), bool(status.stdout.strip())


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
