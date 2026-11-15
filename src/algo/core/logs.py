# ruff: noqa: E501
"""Structured JSON logging with correlation ids. One JSON object per line; the time comes from an injected Clock, never the system clock.

    with logs.correlate(run_id=..., strategy_id=...):      # every line logged inside carries these fields
        log.info("decided")
    log.info("filled", extra={"order_id": "o1"})            # or per line

Only the fields in CORRELATION_FIELDS may be used, so the schema cannot drift; anything else passed as `extra` is rejected by `logging` itself
when it collides with a record attribute and is otherwise written as given (unserialisable values become their repr)."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from algo.core.clock import Clock

BASE_FIELDS = ("ts", "level", "logger", "msg")
CORRELATION_FIELDS = ("run_id", "strategy_id", "instrument_id", "order_id")
_context: ContextVar[dict[str, Any] | None] = ContextVar("log_context", default=None)
_STANDARD = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime"}


@contextmanager
def correlate(**ids: Any) -> Iterator[None]:
    unknown = set(ids) - set(CORRELATION_FIELDS)
    if unknown:
        raise ValueError(
            f"unknown correlation field(s) {sorted(unknown)}; allowed: {CORRELATION_FIELDS}"
        )
    token = _context.set({**(_context.get() or {}), **ids})
    try:
        yield
    finally:
        _context.reset(token)


class JsonFormatter(logging.Formatter):
    def __init__(self, clock: Clock) -> None:
        super().__init__()
        self.clock = clock

    def format(self, record: logging.LogRecord) -> str:
        doc: dict[str, Any] = {
            "ts": self.clock.now().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        doc.update(_context.get() or {})
        doc.update({k: v for k, v in record.__dict__.items() if k not in _STANDARD})
        if record.exc_info:
            doc["exc"] = self.formatException(record.exc_info)
        return json.dumps(doc, default=repr)


def setup(clock: Clock, level: str = "INFO") -> None:
    """Route the root logger through one JSON handler (safe to call twice)."""
    root = logging.getLogger()
    root.handlers[:] = [h for h in root.handlers if not isinstance(h.formatter, JsonFormatter)]
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(clock))
    root.addHandler(handler)
    root.setLevel(level)
