# ruff: noqa: E501
"""A small secret scanner for tracked files (pre-commit and CI run it; a test fails when a secret is seeded). A finding never repeats the secret.
Not a replacement for gitleaks' breadth: it covers the shapes this project can plausibly leak (cloud keys, private keys, tokens, assigned secrets).
Mark a deliberate fixture line with `# secret-scan: allow`."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

PATTERNS = (
    ("aws access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    (
        "assigned secret",
        re.compile(
            r"""(?i)\b(?:api[_-]?key|api[_-]?secret|secret|password|passwd|token)\b\s*[:=]\s*['"]([A-Za-z0-9/+_\-]{20,})['"]"""
        ),
    ),
)
PLACEHOLDERS = ("changeme", "example", "placeholder", "xxxx", "your")
ALLOW = "secret-scan: allow"
WEAK = "assigned secret"  # a name-and-quoted-value guess: skipped in test code, where throwaway passwords are normal


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str

    def show(self) -> str:
        return f"{self.path}:{self.line}: {self.kind}"


def scan_text(path: str, text: str) -> list[Finding]:
    out = []
    in_tests = path.startswith(("tests/", "frontend/tests/"))
    for n, line in enumerate(text.splitlines(), 1):
        if ALLOW in line:
            continue
        for kind, rx in PATTERNS:
            if kind == WEAK and in_tests:
                continue
            m = rx.search(line)
            if m and not (m.groups() and any(p in m.group(1).lower() for p in PLACEHOLDERS)):
                out.append(Finding(path, n, kind))
                break
    return out


def scan_files(root: Path, paths: list[str]) -> list[Finding]:
    out: list[Finding] = []
    for p in paths:
        f = root / p
        if not f.is_file():
            continue
        try:
            text = f.read_text()
        except (UnicodeDecodeError, OSError):
            continue  # binary files are not scanned
        out += scan_text(p, text)
    return out


def tracked(root: Path) -> list[str]:
    return subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.split("\n")[:-1]
