# ruff: noqa: E501
"""ASGI entry point:
  ALGO_DB_URL=postgresql://... uv run uvicorn --factory algo.api.main:build --host 127.0.0.1
Every route except /api/health and sign-in needs a signed-in session (algo.api.security). Required environment:
ALGO_VAULT_KEYS / ALGO_VAULT_CURRENT (the key ring for stored secrets). Optional: ALGO_COOKIE_SECURE=0 for plain-HTTP
local development, ALGO_TRUST_PROXY=1 when a reverse proxy in front appends the real client address.
Reads the connection string, the docs directory holding the frozen benchmark releases, the allowed
browser origins and ALGO_API_DOCS=1 (interactive docs, off by default) from the environment. The
API is read-only except review decisions (ALGO_REVIEW_WRITES=1, off by default), which append to
one table; every other session is read-only with a statement timeout."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from algo.api.app import create_app
from algo.api.security import PortalSettings
from algo.core.clock import SystemClock
from algo.portal.crypto import KeyRing
from algo.portal.passwords import Hasher


def build() -> FastAPI:
    dsn = os.environ.get("ALGO_DB_URL")
    if not dsn:
        raise RuntimeError("ALGO_DB_URL is not set")
    docs = Path(os.environ.get("ALGO_DOCS_DIR", "docs"))
    origins = tuple(
        o.strip()
        for o in os.environ.get("ALGO_CORS_ORIGINS", "http://localhost:3000").split(",")
        if o.strip()
    )
    portal = PortalSettings(
        hasher=Hasher(),
        ring=KeyRing.from_env(os.environ),  # refuses to start without a valid key ring
        clock=SystemClock(),
        origins=origins,
        cookie_secure=os.environ.get("ALGO_COOKIE_SECURE", "1") != "0",
        trust_proxy=os.environ.get("ALGO_TRUST_PROXY") == "1",
    )
    return create_app(
        dsn,
        docs,
        origins,
        portal=portal,
        interactive_docs=os.environ.get("ALGO_API_DOCS") == "1",
        review_writes=os.environ.get("ALGO_REVIEW_WRITES") == "1",
    )
