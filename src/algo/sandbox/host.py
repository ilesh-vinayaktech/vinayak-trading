# ruff: noqa: E501
"""The platform side of the sandbox: starts a strategy worker, talks to it, and supervises it.

The process boundary is the real isolation: a separate process in its own session with a cleared environment (no database or
broker credentials), memory / CPU / process / file-size limits, no network namespace, a working directory that is empty and
temporary, and a wall-clock timeout per call. A worker that breaks a rule, runs out of time or memory, or dies is killed and
the strategy is HALTED: the platform keeps running and the strategy gets no further calls until a person starts a new one.
The same class serves backtest, paper and live runners: they differ only in the Context they pass."""

from __future__ import annotations

import ctypes
import os
import resource
import select
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import algo
from algo.sandbox.protocol import ProtocolError, dumps, loads

CLONE_NEWUSER, CLONE_NEWNET = 0x10000000, 0x40000000


class SandboxError(Exception):
    kind = "error"


class SandboxTimeout(SandboxError):
    kind = "timeout"


class SandboxCrash(SandboxError):
    kind = "crash"


class SandboxViolationError(SandboxError):
    kind = "violation"


class SandboxMemoryError(SandboxError):
    kind = "memory"


class StrategyFailed(SandboxError):
    kind = "exception"


class StrategyHalted(SandboxError):
    kind = "halted"


@dataclass(frozen=True)
class Limits:
    call_timeout_s: float = 10.0
    memory_bytes: int = (
        2 * 1024**3
    )  # address space: Python and pydantic map a few hundred MB before the strategy runs
    cpu_s: int = 60
    max_processes: int = (
        1  # the user's process count already exceeds this, so no fork or thread can succeed
    )
    max_open_files: int = 64
    block_network: bool = True


def isolate(limits: Limits) -> None:
    """Runs in the child between fork and exec."""
    resource.setrlimit(resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes))
    resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_s, limits.cpu_s))
    resource.setrlimit(resource.RLIMIT_NPROC, (limits.max_processes, limits.max_processes))
    resource.setrlimit(resource.RLIMIT_NOFILE, (limits.max_open_files, limits.max_open_files))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if limits.block_network:
        uid, gid = os.getuid(), os.getgid()
        if ctypes.CDLL(None, use_errno=True).unshare(CLONE_NEWUSER | CLONE_NEWNET) != 0:
            os._exit(
                125
            )  # the namespace could not be made: better no worker than one with a network
        with open("/proc/self/setgroups", "w") as f:
            f.write("deny")
        with open("/proc/self/uid_map", "w") as f:
            f.write(f"0 {uid} 1")
        with open("/proc/self/gid_map", "w") as f:
            f.write(f"0 {gid} 1")


def spawn(argv: Sequence[str], limits: Limits, *, cwd: str, stderr: Any) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        list(argv),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=stderr,
        cwd=cwd,
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHONHASHSEED": "0",
        },  # nothing of ours: no database URL, no vault key, no token
        close_fds=True,
        start_new_session=True,
        preexec_fn=lambda: isolate(limits),  # noqa: PLW1509
    )


class SandboxedStrategy:
    def __init__(
        self,
        spec: str,
        params: dict[str, Any],
        *,
        args: Sequence[Any] = (),
        import_roots: Sequence[Path] = (),
        read_roots: Sequence[Path] = (),
        state: Any = None,
        limits: Limits | None = None,
        on_halt: Callable[[str], None] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.spec, self.params, self.args = spec, params, list(args)
        self.import_roots = [str(r) for r in import_roots]  # added to sys.path in the worker
        platform = str(
            Path(algo.__file__).resolve().parents[1]
        )  # the platform's own code is always readable
        self.read_roots = [
            platform,
            *(str(r) for r in (read_roots or import_roots)),
        ]  # the only places it may read files from
        self.state, self.limits, self.on_halt, self._monotonic = (
            state,
            limits or Limits(),
            on_halt,
            monotonic,
        )
        self.failed: str | None = None
        self.detail = ""
        self.identity: dict[str, str] = {}
        self._proc: subprocess.Popen[bytes] | None = None
        self._buf = b""
        self._tmp = tempfile.TemporaryDirectory(prefix="algo-sandbox-")
        self._err = tempfile.TemporaryFile()

    # --- process ----------------------------------------------------------------------------------------------------
    def start(self) -> None:
        if self.failed:
            raise StrategyHalted(self.failed)
        self._proc = spawn(
            [sys.executable, "-I", "-B", "-m", "algo.sandbox.worker"],
            self.limits,
            cwd=self._tmp.name,
            stderr=self._err,
        )
        self._send(
            {
                "op": "init",
                "spec": self.spec,
                "params": self.params,
                "args": self.args,
                "state": self.state,
                "sys_path": self.import_roots,
                "read_roots": self.read_roots,
            }
        )
        reply = self._recv(self._monotonic() + self.limits.call_timeout_s)
        if not reply["ok"]:
            self._fail(reply)
        self.identity = reply["result"]

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, 9)
            except ProcessLookupError:  # already gone
                pass
        if proc is not None:
            proc.wait()
            for f in (proc.stdin, proc.stdout):
                if f is not None:
                    f.close()
        self._err.close()
        self._tmp.cleanup()

    def _stderr_tail(self) -> str:
        self._err.seek(0)
        return self._err.read()[-600:].decode(errors="replace").strip()

    def _halt(self, why: str) -> None:
        self.failed = why
        self.stop()
        if self.on_halt is not None:
            self.on_halt(why)

    def _fail(self, reply: dict[str, Any]) -> None:
        kind, error = reply.get("kind", "exception"), str(reply.get("error"))
        self.detail = str(
            reply.get("detail", "")
        )  # where it happened, for whoever has to fix the strategy
        if kind == "exception" and self._proc is not None and self.identity:
            raise StrategyFailed(
                error
            )  # the strategy raised an ordinary error: the worker is fine, the call failed
        self._halt(f"{kind}: {error}")
        raise {"violation": SandboxViolationError, "memory": SandboxMemoryError}.get(
            kind, StrategyFailed
        )(error)

    # --- wire -------------------------------------------------------------------------------------------------------
    def _send(self, msg: dict[str, Any]) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        try:
            self._proc.stdin.write((dumps(msg) + "\n").encode())
            self._proc.stdin.flush()
        except (BrokenPipeError, ValueError):
            self._die("the worker is gone")

    def _die(self, what: str) -> None:
        code = None
        if self._proc is not None:
            try:
                code = self._proc.wait(
                    timeout=2
                )  # the pipe closes a moment before the process is reaped
            except subprocess.TimeoutExpired:
                pass
        tail = self._stderr_tail()
        self._halt(f"crash: {what} (exit code {code}) {tail}".strip())
        raise SandboxCrash(self.failed)

    def _recv(self, deadline: float) -> dict[str, Any]:
        assert self._proc is not None and self._proc.stdout is not None
        fd = self._proc.stdout.fileno()
        while b"\n" not in self._buf:
            wait = deadline - self._monotonic()
            if wait <= 0 or not select.select([fd], [], [], wait)[0]:
                self._halt(f"timeout: no answer within {self.limits.call_timeout_s} s")
                raise SandboxTimeout(self.failed)
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                self._die("the worker exited")
            self._buf += chunk
        line, _, self._buf = self._buf.partition(b"\n")
        try:
            return loads(line.decode())
        except ProtocolError as e:
            self._halt(f"crash: the worker sent garbage: {e}")
            raise SandboxCrash(self.failed) from e

    # --- use --------------------------------------------------------------------------------------------------------
    def call(self, method: str, ctx: Any) -> Any:
        """Run one strategy method with a platform Context (`ctx.now()`, `ctx.data.history`, `ctx.portfolio`, `ctx.mode`)."""
        if self.failed:
            raise StrategyHalted(self.failed)
        if self._proc is None:
            self.start()
        deadline = self._monotonic() + self.limits.call_timeout_s
        p = ctx.portfolio
        self._send(
            {
                "op": "call",
                "method": method,
                "ctx": {
                    "now": ctx.now(),
                    "mode": ctx.mode,
                    "portfolio": {
                        "cash": p.cash,
                        "equity": p.equity,
                        "positions": {str(k): v for k, v in p.positions.items()},
                    },
                },
            }
        )
        while True:
            msg = self._recv(deadline)
            if msg.get("op") == "history":
                bars = ctx.data.history(msg["ids"], msg["lookback"], adjusted=msg["adjusted"])
                self._send({"ok": True, "result": {str(k): v for k, v in bars.items()}})
                continue
            if not msg["ok"]:
                self._fail(msg)
            break
        self._send({"op": "get_state"})
        self.state = self._recv(deadline)[
            "result"
        ]  # kept so a replacement worker can carry on from here
        return self._decode(method, msg["result"])

    def audit(self) -> dict[str, Any]:
        """The strategy's latest audit row (what it saw and decided), integer keys restored."""
        from algo.sandbox.adapters import restore_audit

        if self.failed:
            raise StrategyHalted(self.failed)
        self._send({"op": "get_audit"})
        reply = self._recv(self._monotonic() + self.limits.call_timeout_s)
        return restore_audit(reply["result"])

    @staticmethod
    def _decode(method: str, result: Any) -> Any:
        if method == "on_schedule" and result is not None:
            return {int(k): Decimal(v) for k, v in result.items()}
        return result
