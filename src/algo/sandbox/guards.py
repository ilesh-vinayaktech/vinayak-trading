# ruff: noqa: E501
"""What a strategy worker may not do, decided from Python's audit events (PEP 578). `decide` is a pure function of the event
and a Policy so every rule can be tested; `install` arms it in the worker process.

HONEST LIMIT: an audit hook is defence in depth inside one process, not a security boundary: native code could step around
it. The boundary is the operating-system side in host.py (separate process, scrubbed environment, resource limits, network
namespace, no credentials anywhere in reach). These rules make the common mistakes and the lazy attacks fail loudly."""

from __future__ import annotations

import ast
import os
import sys
from dataclasses import dataclass, field
from typing import Any


class SandboxViolation(BaseException):
    """BaseException on purpose: a strategy's `except Exception` must not be able to swallow it."""


@dataclass
class Policy:
    read_roots: tuple[str, ...]
    denied_imports: frozenset[str] = field(
        default_factory=frozenset
    )  # empty while the strategy is being loaded
    violation: str | None = (
        None  # the first thing refused, kept even if the strategy swallows the exception
    )


_PROCESS = {
    "subprocess.Popen",
    "os.system",
    "os.exec",
    "os.fork",
    "os.forkpty",
    "os.posix_spawn",
    "os.spawn",
    "os.kill",
    "os.killpg",
}
_CHANGE = {
    "os.remove",
    "os.rename",
    "os.mkdir",
    "os.rmdir",
    "os.chmod",
    "os.chown",
    "os.link",
    "os.symlink",
    "os.truncate",
    "os.mkfifo",
    "os.mknod",
    "os.utime",
}
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


def _under(path: str, roots: tuple[str, ...]) -> bool:
    real = os.path.realpath(path)
    return any(
        real == r or real.startswith(r.rstrip("/") + "/")
        for r in (os.path.realpath(x) for x in roots)
    )


def decide(event: str, args: tuple[Any, ...], policy: Policy) -> str | None:
    """The reason this event is refused, or None."""
    if event.startswith("socket."):
        return "network access is not allowed"
    if event in _PROCESS:
        return "starting or signalling processes is not allowed"
    if event.startswith("ctypes."):
        return "native code is not allowed"
    if event in _CHANGE or event.startswith("shutil."):
        return "a strategy may not change files"
    if event == "import":
        name = str(args[0]).split(".")[0]
        return f"import of {args[0]} is not allowed" if name in policy.denied_imports else None
    if event == "open":
        path, mode, flags = args[0], args[1], args[2]
        if isinstance(path, int):
            return None
        if (isinstance(mode, str) and set(mode) & set("wax+")) or (
            isinstance(flags, int) and flags & _WRITE_FLAGS
        ):
            return "a strategy may not write files"
        if not _under(os.fsdecode(path), policy.read_roots):
            return f"reading {os.fsdecode(path)} is outside the allowed paths"
    return None


def install(policy: Policy) -> None:
    def hook(event: str, args: tuple[Any, ...]) -> None:
        reason = decide(event, args, policy)
        if reason is not None:
            policy.violation = policy.violation or reason
            raise SandboxViolation(reason)

    sys.addaudithook(hook)


_CLOCK_OBJECTS = {"datetime", "date", "dt"}


def scan_source(source: str) -> list[str]:
    """Calls of the system clock in strategy source (a strategy gets its time from ctx.now()). A static check of the
    strategy's own file, a guard against the honest mistake; the platform's clock is injected, never read."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [f"line {e.lineno or 1}: syntax error, cannot be checked: {e.msg}"]
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr, base = node.func.attr, node.func.value
            base_name = (
                base.id
                if isinstance(base, ast.Name)
                else base.attr
                if isinstance(base, ast.Attribute)
                else ""
            )
            if (attr in ("now", "utcnow", "today") and base_name in _CLOCK_OBJECTS) or (
                attr in ("time", "time_ns") and base_name == "time"
            ):
                found.append(
                    f"line {node.lineno}: {base_name}.{attr}() reads the system clock; use ctx.now()"
                )
    return sorted(found, key=lambda f: int(f.split(":")[0].split()[1]))
