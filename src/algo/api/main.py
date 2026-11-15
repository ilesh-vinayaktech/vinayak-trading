# ruff: noqa: E501
"""ASGI entry point:
  ALGO_DB_URL=postgresql://... uv run uvicorn --factory algo.api.main:build --host 127.0.0.1
Every route except /api/health and sign-in needs a signed-in session (algo.api.security). Required environment:
ALGO_VAULT_KEYS / ALGO_VAULT_CURRENT (the key ring for stored secrets). Optional: ALGO_COOKIE_SECURE=0 for plain-HTTP
local development, ALGO_PUBLIC_URL (the address links in mails point to), ALGO_TRUST_PROXY=1 when a reverse proxy in front appends the real client address.
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
from algo.core.settings import Settings
from algo.portal.crypto import KeyRing
from algo.portal.passwords import Hasher


def build() -> FastAPI:
    if not os.environ.get("ALGO_DB_URL"):
        raise RuntimeError("ALGO_DB_URL is not set")
    cfg = Settings.from_env(os.environ)  # refuses an invalid value, naming the variable
    docs = Path(os.environ.get("ALGO_DOCS_DIR", "docs"))
    portal = PortalSettings(
        hasher=Hasher(),
        ring=KeyRing.from_env(os.environ),  # refuses to start without a valid key ring
        clock=SystemClock(),
        origins=cfg.cors_origins,
        cookie_secure=cfg.cookie_secure,
        trust_proxy=cfg.trust_proxy,
        public_url=cfg.public_url,
    )
    return create_app(
        cfg.db_url,
        docs,
        cfg.cors_origins,
        portal=portal,
        interactive_docs=os.environ.get("ALGO_API_DOCS") == "1",
        review_writes=os.environ.get("ALGO_REVIEW_WRITES") == "1",
    )
