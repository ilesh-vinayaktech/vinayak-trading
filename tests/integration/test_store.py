from decimal import Decimal as D

import pytest

from algo.backtest.engine import CostModel, run_backtest
from algo.backtest.store import save_run, summary
from algo.data.review import verify
from algo.strategy.base import Mode
from algo.strategy.lifecycle import promotion_blockers
from tests.support.bt import (
    DAYS,
    NOW,
    add_action,
    cfg,
    flat,
    hold,
    make_env,
    provisional_demerger,
    put_bars,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def env(conn):
    return make_env(conn)


def test_a_run_is_persisted_with_everything_needed_to_judge_it(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    provisional_demerger(conn, a, DAYS[6])
    r = run_backtest(conn, hold((a, 1)), cfg(mode=Mode.RESEARCH, cost=CostModel("t", D(10), D(5), True)),
                     code_version="abc123")  # fmt: skip
    run_id = save_run(conn, r, NOW)
    row = conn.execute(
        "SELECT strategy_id, params_hash, code_version, reader_mode, accounting_complete, result_hash,"
        " jsonb_array_length(provisional_events), adjustment_versions->>%s, cost_model->>'placeholder'"
        " FROM backtest_run WHERE run_id=%s",
        (str(a), run_id),
    ).fetchone()
    assert row[:7] == ("hold", r.params_hash, "abc123", "research", False, r.result_hash, 1)
    assert row[7] == r.adjustment_versions[a] and row[8] == "true"
    assert conn.execute(
        "SELECT count(*) FROM backtest_trade WHERE run_id=%s", (run_id,)
    ).fetchone()[0] == len(r.trades)
    assert (
        conn.execute("SELECT count(*) FROM backtest_equity WHERE run_id=%s", (run_id,)).fetchone()[
            0
        ]
        == 10
    )


def test_a_research_run_can_never_support_promotion_but_a_clean_strict_validated_one_can(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    research = save_run(conn, run_backtest(conn, hold((a, 1)), cfg(mode=Mode.RESEARCH)), NOW)
    blockers = promotion_blockers(summary(conn, research, validation_protocol_passed=True))
    assert blockers == ["run was not made in strict reader mode"]
    strict = save_run(conn, run_backtest(conn, hold((a, 1)), cfg(mode=Mode.STRICT)), NOW)
    assert promotion_blockers(summary(conn, strict, validation_protocol_passed=True)) == []
    assert promotion_blockers(summary(conn, strict)) != []  # validation protocol still required


def test_placeholder_costs_and_provisional_estimates_block_promotion(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    provisional_demerger(conn, a, DAYS[6])
    rid = save_run(
        conn,
        run_backtest(
            conn, hold((a, 1)), cfg(mode=Mode.RESEARCH, cost=CostModel("p", D(1), D(1), True))
        ),
        NOW,
    )
    out = promotion_blockers(summary(conn, rid, validation_protocol_passed=True))
    assert any("strict" in x for x in out) and any("provisional" in x for x in out)
    assert any("placeholder" in x for x in out) and any("model" in x for x in out)
    with pytest.raises(LookupError):
        summary(conn, 999999)


def test_verified_factor_runs_in_strict_mode_but_a_held_demerger_still_blocks_promotion(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    provisional_demerger(conn, a, DAYS[6])
    verify(conn, symbol="AAA", ex_date=DAYS[6], kind="demerger", by="owner", now=NOW,
           source_type="company_filing", source_url="https://example.org/x")  # fmt: skip
    r = run_backtest(conn, hold((a, 1)), cfg(mode=Mode.STRICT))
    assert r.blocked == {} and r.provisional == [] and not r.accounting_complete
    rid = save_run(conn, r, NOW)
    assert promotion_blockers(summary(conn, rid, validation_protocol_passed=True)) == [
        "held positions passed through corporate actions the accounting cannot model"
    ]


# ---- the ledger is persisted as the canonical record ---------------------------------------------
def test_the_ledger_is_persisted_and_the_view_matches_the_run_pnl(env):
    conn, a, _ = env
    put_bars(conn, a, {**flat(100, DAYS[:2]), **flat(110, DAYS[2:])})
    add_action(conn, a, DAYS[6], "dividend", amount=D(1))
    r = run_backtest(conn, hold((a, 1)), cfg(cost=CostModel("t", D(10), D(0), False)))
    run_id = save_run(conn, r, NOW)
    n = conn.execute("SELECT count(*) FROM backtest_ledger WHERE run_id=%s", (run_id,)).fetchone()[
        0
    ]
    assert n == len(r.ledger.entries) and n > 4
    realized, dividends, fees, cash = conn.execute(
        "SELECT realized, dividends, fees, cash_balance FROM backtest_ledger_pnl WHERE run_id=%s",
        (run_id,),
    ).fetchone()
    assert (realized, dividends, fees) == (
        D(r.pnl["realized"]),
        D(r.pnl["dividends"]),
        D(r.pnl["fees"]),
    )
    assert cash == r.final_cash  # the cash ledger sums to the final balance
    row = conn.execute(
        "SELECT ledger_reconciled, reconciliation, pnl FROM backtest_run WHERE run_id=%s", (run_id,)
    ).fetchone()
    assert row[0] is True and row[1] == [] and row[2] == r.pnl


def test_every_persisted_entry_cites_its_source_event(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    run_id = save_run(conn, run_backtest(conn, hold((a, 1)), cfg()), NOW)
    refs = {
        r[0]
        for r in conn.execute("SELECT DISTINCT ref FROM backtest_ledger WHERE run_id=%s", (run_id,))
    }
    assert refs == {"initial", "trade:1"}


def test_a_run_whose_ledger_does_not_reconcile_cannot_support_promotion(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    r = run_backtest(conn, hold((a, 1)), cfg(mode=Mode.STRICT))
    good = save_run(conn, r, NOW)
    assert promotion_blockers(summary(conn, good, validation_protocol_passed=True)) == []
    r.reconciliation = ["cash: running 1 != entries 2"]  # as if the books had disagreed
    bad = save_run(conn, r, NOW)
    assert promotion_blockers(summary(conn, bad, validation_protocol_passed=True)) == [
        "financial ledger does not reconcile"
    ]
    stored = conn.execute(
        "SELECT reconciliation FROM backtest_run WHERE run_id=%s", (bad,)
    ).fetchone()[0]
    assert stored == ["cash: running 1 != entries 2"]
