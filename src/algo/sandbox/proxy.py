# ruff: noqa: E501
"""A strategy for the backtest engine whose decisions are made in the sandbox worker (spec section 9: the same worker in backtest, paper
and live). The engine only ever calls `universe`, `on_start` and `on_schedule`, and reads the identity (`id`, `version`, `params`,
`params_hash`) and `requirements()`: the identity and requirements come from the in-process `strategy` (plain configuration), the three
decision methods run in the worker, which asks the platform for history through the real `Context` as of `ctx.now()`.
The worker starts on the first call; `close()` stops it."""

from __future__ import annotations

from typing import Any

from algo.sandbox.host import SandboxedStrategy
from algo.strategy.base import Strategy


class SandboxedProxy:
    def __init__(self, strategy: Strategy, worker: SandboxedStrategy) -> None:
        self._strategy, self._worker = strategy, worker

    def __getattr__(self, name: str) -> Any:  # id, version, params, params_hash, requirements
        return getattr(self._strategy, name)

    def universe(self, ctx: Any) -> list[int]:
        return [int(i) for i in self._worker.call("universe", ctx)]

    def on_start(self, ctx: Any) -> None:
        self._worker.call("on_start", ctx)

    def on_schedule(self, ctx: Any) -> Any:
        return self._worker.call("on_schedule", ctx)

    def close(self) -> None:
        self._worker.stop()
