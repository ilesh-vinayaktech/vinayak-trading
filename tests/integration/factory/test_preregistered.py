# ruff: noqa: E501
"""Registering the pre-registered definitions on a real database: once each, immutable, and visible to the study link."""

from datetime import UTC, datetime

import pytest

from algo.data.store.migrate import migrate
from algo.factory import preregistered, registry

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 16, 12, tzinfo=UTC)


def test_each_definition_is_registered_once_and_a_second_run_writes_nothing(conn):
    migrate(conn)
    assert preregistered.register_all(conn, by="owner", now=NOW) == [
        "MOMENTUM_12M_M",
        "MOMENTUM_LOWVOL_M",
        "MOMENTUM_TREND_M",
    ]
    assert preregistered.register_all(conn, by="owner", now=NOW) == []
    got = registry.get(conn, "MOMENTUM_TREND_M", 1)
    assert got.sha256 == preregistered.definitions()[2].sha256  # stored exactly as written
    by, reason = conn.execute(
        "SELECT created_by, reason FROM strategy_definition WHERE strategy_id='MOMENTUM_12M_M'"
    ).fetchone()
    assert by == "owner" and "before any result" in reason


def test_the_script_registers_them_and_says_so(conn, pg_url, monkeypatch, capsys):
    import runpy
    import sys
    from pathlib import Path

    migrate(conn)
    conn.commit()
    monkeypatch.setattr(sys, "argv", ["register_preregistered.py", "--db", pg_url])
    runpy.run_path(
        str(Path(__file__).parents[3] / "scripts/register_preregistered.py"), run_name="__main__"
    )
    assert (
        "registered MOMENTUM_12M_M, MOMENTUM_LOWVOL_M, MOMENTUM_TREND_M" in capsys.readouterr().out
    )
    runpy.run_path(
        str(Path(__file__).parents[3] / "scripts/register_preregistered.py"), run_name="__main__"
    )
    assert "registered nothing new" in capsys.readouterr().out
