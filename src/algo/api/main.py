"""ASGI entry point:  ALGO_DB_URL=postgresql://... uv run uvicorn --factory algo.api.main:build
Reads the connection string, the docs directory holding the frozen benchmark releases, and the
allowed browser origins from the environment. The API is read-only."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from algo.api.app import create_app


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
    return create_app(dsn, docs, origins)
