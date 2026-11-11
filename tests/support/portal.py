"""Test factories for the API. `open_app` is for tests of the research endpoints themselves: it replaces the sign-in guard
(FastAPI's standard dependency_overrides; production code has no bypass flag). `make_app` keeps the real guard."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from algo.api.app import create_app
from algo.api.security import PortalSettings, guard
from algo.core.clock import SimClock
from algo.portal.crypto import KeyRing
from algo.portal.passwords import Hasher

ORIGIN = "http://localhost:3000"
RING = KeyRing.from_env(
    {"ALGO_VAULT_KEYS": "v1:" + base64.b64encode(b"k" * 32).decode(), "ALGO_VAULT_CURRENT": "v1"}
)
FAST = Hasher(
    time_cost=1, memory_cost=8, parallelism=1
)  # tests only: the real defaults are deliberately slow


def settings(clock: Any = None, **kw: Any) -> PortalSettings:
    return PortalSettings(
        FAST,
        RING,
        clock or SimClock(datetime(2026, 11, 11, 10, 0, tzinfo=UTC)),
        (ORIGIN,),
        cookie_secure=False,
        **kw,
    )


def make_app(dsn: str, docs: Path, *, portal: PortalSettings | None = None, **kw: Any) -> FastAPI:
    return create_app(dsn, docs, portal=portal or settings(), **kw)


def open_app(dsn: str, docs: Path, **kw: Any) -> FastAPI:
    app = make_app(dsn, docs, **kw)
    app.dependency_overrides[guard] = lambda: None
    return app
