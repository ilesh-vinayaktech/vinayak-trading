# ruff: noqa: E501
"""The strategy worker: runs as its own process (`python -I -B -m algo.sandbox.worker`), speaks protocol.py on stdin/stdout.

It holds no credentials (the environment is cleared), cannot reach the network, start processes, write files or read outside
the allowed roots (guards.py), and cannot read the system clock. A strategy asks the platform for history through the protocol
(`ctx.data.history` is a question to the host, answered as of ctx.now()), and its only output is Targets."""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import sysconfig
import time
import traceback
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any

from algo.sandbox.guards import Policy, SandboxViolation, install, scan_source
from algo.sandbox.protocol import dumps, loads

DENIED_AFTER_LOAD = frozenset(
    {
        "subprocess",
        "ctypes",
        "multiprocessing",
        "socket",
        "requests",
        "urllib3",
        "http",
        "ftplib",
        "smtplib",
        "sqlite3",
        "psycopg",
        "shutil",
        "pty",
    }
)


def _no_clock(*_a: Any, **_k: Any) -> float:
    raise SandboxViolation("the system clock is not available to a strategy; use ctx.now()")


class _Data:
    def __init__(self, ask: Any) -> None:
        self._ask = ask

    def history(
        self, instrument_ids: Any, lookback_days: int, *, adjusted: bool = True
    ) -> dict[int, list[Any]]:
        reply = self._ask(
            {
                "op": "history",
                "ids": [int(i) for i in instrument_ids],
                "lookback": lookback_days,
                "adjusted": adjusted,
            }
        )
        return {int(k): v for k, v in reply.items()}


class _Ctx:
    def __init__(self, c: dict[str, Any], ask: Any) -> None:
        self._now = c["now"]
        self.mode = c["mode"]
        p = c["portfolio"]
        self.portfolio = SimpleNamespace(
            cash=p["cash"],
            positions=MappingProxyType({int(k): v for k, v in p["positions"].items()}),
            equity=p["equity"],
        )
        self.data = _Data(ask)

    def now(self) -> Any:
        return self._now


def main() -> None:
    inp = sys.stdin
    out = os.fdopen(os.dup(1), "w", buffering=1)
    os.dup2(2, 1)  # a print() in a strategy goes to stderr and can never corrupt the protocol

    def send(msg: dict[str, Any]) -> None:
        out.write(dumps(msg) + "\n")
        out.flush()

    def recv() -> dict[str, Any]:
        line = inp.readline()
        if not line:
            raise SystemExit(0)  # the platform closed the pipe
        return loads(line)

    def ask(msg: dict[str, Any]) -> Any:
        send(msg)
        reply = recv()
        if not reply.get("ok"):
            raise RuntimeError(str(reply.get("error")))
        return reply["result"]

    init = recv()
    os.environ.clear()
    sys.path[:0] = list(init["sys_path"])
    paths = sysconfig.get_paths()
    roots = {
        *init["read_roots"],
        sys.prefix,
        sys.base_prefix,
        sys.exec_prefix,
        *(paths[k] for k in ("stdlib", "platstdlib", "purelib", "platlib")),
    }
    policy = Policy(read_roots=tuple(sorted(roots)))
    install(policy)
    time.time = time.time_ns = _no_clock  # type: ignore[assignment]
    try:
        module_name, cls_name = init["spec"].split(":")
        found = importlib.util.find_spec(module_name)
        findings = scan_source(Path(found.origin).read_text()) if found and found.origin else []
        if findings:
            send({"ok": False, "kind": "violation", "error": "; ".join(findings)})
            return
        cls = getattr(importlib.import_module(module_name), cls_name)
        strategy = cls(cls.Params(**init["params"]), *init["args"])
        if init.get("state") is not None and hasattr(strategy, "set_state"):
            strategy.set_state(init["state"])
    except SandboxViolation as e:
        send({"ok": False, "kind": "violation", "error": str(e)})
        return
    except Exception as e:
        send(
            {
                "ok": False,
                "kind": "exception",
                "error": f"cannot load {init['spec']}: {type(e).__name__}: {e}",
            }
        )
        return
    for name in [m for m in sys.modules if m.split(".")[0] in DENIED_AFTER_LOAD]:
        sys.modules[name] = None  # type: ignore[assignment]  # whatever the platform needed to load, a new `import` of it fails now
    policy.denied_imports = DENIED_AFTER_LOAD
    send({"ok": True, "result": {"id": strategy.id, "version": strategy.version}})

    while True:
        msg = recv()
        op = msg["op"]
        try:
            if op == "get_state":
                result: Any = strategy.get_state() if hasattr(strategy, "get_state") else None
            elif op == "call":
                ctx = _Ctx(msg["ctx"], ask)
                result = _call(strategy, msg["method"], ctx)
            else:
                raise RuntimeError(f"unknown op {op!r}")
        except SandboxViolation as e:
            send({"ok": False, "kind": "violation", "error": str(e)})
            return  # a worker that broke a rule is never reused
        except MemoryError:
            send({"ok": False, "kind": "memory", "error": "the strategy ran out of memory"})
            return
        except Exception as e:
            send(
                {
                    "ok": False,
                    "kind": "exception",
                    "error": f"{type(e).__name__}: {e}",
                    "detail": traceback.format_exc()[-1500:],
                }
            )
            continue
        if policy.violation:  # the strategy caught the exception: it still broke the rule
            send({"ok": False, "kind": "violation", "error": policy.violation})
            return
        send({"ok": True, "result": result})


def _call(strategy: Any, method: str, ctx: _Ctx) -> Any:
    if method == "universe":
        return [int(i) for i in strategy.universe(ctx)]
    if method == "requirements":
        r = strategy.requirements()
        return {"lookback_days": r.lookback_days, "adjust": r.adjust}
    if method == "on_start":
        strategy.on_start(ctx)
        return None
    if method == "on_schedule":
        targets = strategy.on_schedule(ctx)
        if targets is not None and not (
            isinstance(targets, dict)
            and all(isinstance(k, int) and isinstance(v, Decimal) for k, v in targets.items())
        ):
            raise TypeError(
                f"a strategy returns Targets ({{instrument_id: Decimal}}) or None, not {type(targets).__name__}"
            )
        return None if targets is None else {str(k): v for k, v in targets.items()}
    raise RuntimeError(f"unknown method {method!r}")


if __name__ == "__main__":
    main()
