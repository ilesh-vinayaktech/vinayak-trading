"""Minimal forward-only SQL migration runner. Files NNN_name.sql applied once, in order."""

from __future__ import annotations

from pathlib import Path

import psycopg

MIGRATIONS = Path(__file__).parent / "migrations"


def migrate(conn: psycopg.Connection) -> list[str]:
    """Apply pending migrations in one transaction each. Returns the names applied."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migration (name TEXT PRIMARY KEY)")
    done = {r[0] for r in conn.execute("SELECT name FROM schema_migration")}
    applied: list[str] = []
    for f in sorted(MIGRATIONS.glob("*.sql")):
        if f.name in done:
            continue
        with conn.transaction():
            conn.execute(f.read_text())
            conn.execute("INSERT INTO schema_migration VALUES (%s)", (f.name,))
        applied.append(f.name)
    return applied
