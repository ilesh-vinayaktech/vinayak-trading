# ruff: noqa: E501
"""Generating strategy definitions from the alpha registry on a real database: only CANDIDATES, once each, every refusal explained."""

from datetime import UTC, datetime

import pytest

from algo.alpha import registry as alpha_registry
from algo.alpha.discover import Evidence
from algo.data.store.migrate import migrate
from algo.factory import generate, registry

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
DS = "d" * 64


def ev(feature, horizon, ic, t, p=0.0001):
    return Evidence(feature, "1", horizon, 500, 150.0, ic, 0.1, ic / 0.1, 0.6, t, p)


def seed(conn):
    migrate(conn)
    alpha_registry.record(
        conn,
        [
            ev("ret_20d", 20, 0.05, 4.0),  # strong, positive: expressible
            ev("vol_20d", 5, -0.05, -4.0),  # strong, negative: expressible
            ev("atr_14d", 20, 0.05, 4.0),  # strong, but a chained feature: refused with the reason
            ev("ret_5d", 5, 0.0, 0.0, p=0.9),  # no effect: REJECTED, never turned into a strategy
        ],
        DS,
        NOW,
    )


def test_every_candidate_becomes_one_registered_definition_and_every_refusal_says_why(conn):
    seed(conn)
    r = generate.generate_from_candidates(conn, by="agent", now=NOW)
    assert sorted(c.strategy_id for c in r.created) == ["ALPHA_RET_20D_H20", "ALPHA_VOL_20D_H5"]
    assert [(x.hypothesis_id, "all of its history" in x.reason) for x in r.refused] == [(3, True)]
    assert r.existing == []
    up = registry.get(conn, "ALPHA_RET_20D_H20", 1)
    assert (
        up.entry.conditions()[0].op == "TOP_PERCENT"
        and registry.get(conn, "ALPHA_VOL_20D_H5", 1).entry.conditions()[0].op == "BOTTOM_PERCENT"
    )
    reason, by = conn.execute(
        "SELECT reason, created_by FROM strategy_definition WHERE strategy_id='ALPHA_RET_20D_H20'"
    ).fetchone()
    assert by == "agent" and "alpha hypothesis 1" in reason and "CANDIDATE" in reason
    assert conn.execute("SELECT count(*) FROM strategy_definition").fetchone() == (
        2,
    )  # the rejected one and the refused one are not stored


def test_running_it_again_creates_nothing_and_a_second_batch_of_the_same_idea_is_not_a_second_strategy(
    conn,
):
    seed(conn)
    generate.generate_from_candidates(conn, by="agent", now=NOW)
    again = generate.generate_from_candidates(conn, by="agent", now=NOW)
    assert (
        again.created == []
        and sorted(again.existing) == ["ALPHA_RET_20D_H20", "ALPHA_VOL_20D_H5"]
        and len(again.refused) == 1
    )
    alpha_registry.record(
        conn, [ev("ret_20d", 20, 0.06, 5.0)], "e" * 64, NOW
    )  # the same feature at the same horizon, retested in a later batch
    third = generate.generate_from_candidates(conn, by="agent", now=NOW)
    assert third.created == [] and conn.execute(
        "SELECT count(*) FROM strategy_definition"
    ).fetchone() == (2,)


def test_a_new_candidate_is_picked_up_on_the_next_run(conn):
    seed(conn)
    generate.generate_from_candidates(conn, by="agent", now=NOW)
    alpha_registry.record(conn, [ev("dist_sma_50d", 60, 0.04, 3.5)], "e" * 64, NOW)
    r = generate.generate_from_candidates(conn, by="agent", now=NOW)
    assert [c.strategy_id for c in r.created] == ["ALPHA_DIST_SMA_50D_H60"]


def test_the_author_is_required_and_an_empty_alpha_registry_generates_nothing(conn):
    migrate(conn)
    assert generate.generate_from_candidates(conn, by="agent", now=NOW) == generate.Report(
        [], [], []
    )
    with pytest.raises(generate.GenerateError, match="who ran it"):
        generate.generate_from_candidates(conn, by=" ", now=NOW)


def run_script(pg_url, monkeypatch, *args):
    import runpy
    import sys
    from pathlib import Path

    monkeypatch.setattr(sys, "argv", ["generate_strategies.py", "--db", pg_url, *args])
    try:
        runpy.run_path(
            str(Path(__file__).parents[3] / "scripts/generate_strategies.py"), run_name="__main__"
        )
        return 0
    except SystemExit as e:
        return e.code


def test_the_script_shows_what_it_would_do_then_registers_it_and_says_what_it_refused(
    conn, pg_url, monkeypatch, capsys
):
    seed(conn)
    conn.commit()
    assert run_script(pg_url, monkeypatch, "--dry-run") == 0
    dry = capsys.readouterr().out
    assert (
        "would register ALPHA_RET_20D_H20 from hypothesis 1" in dry
        and "refused hypothesis 3 (atr_14d at 20 days)" in dry
    )
    assert conn.execute("SELECT count(*) FROM strategy_definition").fetchone() == (
        0,
    )  # a dry run stores nothing
    assert run_script(pg_url, monkeypatch, "--by", "jane") == 0
    out = capsys.readouterr().out
    assert (
        "registered ALPHA_VOL_20D_H5 from hypothesis 2" in out
        and "2 registered, 0 already there, 1 refused" in out
    )
    assert conn.execute("SELECT DISTINCT created_by FROM strategy_definition").fetchall() == [
        ("jane",)
    ]
    assert run_script(pg_url, monkeypatch) == 0
    third = capsys.readouterr().out
    assert (
        "already registered: ALPHA_RET_20D_H20" in third
        and "0 registered, 2 already there, 1 refused" in third
    )
