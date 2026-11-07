from decimal import Decimal as D

import pytest

from algo.backtest.costs.policy import CostModel
from algo.backtest.engine import run_backtest
from algo.backtest.store import save_run, summary
from algo.data.review import verify
from algo.strategy.base import Mode
from algo.strategy.lifecycle import promotion_blockers
from tests.support.bt import (
    DAYS,
    NOW,
    REALISTIC,
    ZERO,
    add_action,
    cfg,
    flat,
    hold,
    make_env,
    provisional_demerger,
    put_bars,
)
from tests.support.strategies import HoldParams, Scripted  # noqa: E402

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
    research = save_run(
        conn, run_backtest(conn, hold((a, 1)), cfg(mode=Mode.RESEARCH, cost=REALISTIC)), NOW
    )
    blockers = promotion_blockers(summary(conn, research, validation_protocol_passed=True))
    assert blockers == ["run was not made in strict reader mode"]
    strict = save_run(
        conn, run_backtest(conn, hold((a, 1)), cfg(mode=Mode.STRICT, cost=REALISTIC)), NOW
    )
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
    r = run_backtest(conn, hold((a, 1)), cfg(mode=Mode.STRICT, cost=REALISTIC))
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
    r = run_backtest(conn, hold((a, 1)), cfg(mode=Mode.STRICT, cost=REALISTIC))
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


def test_a_zero_slippage_run_cannot_support_promotion_even_if_everything_else_is_clean(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    rid = save_run(conn, run_backtest(conn, hold((a, 1)), cfg(mode=Mode.STRICT, cost=ZERO)), NOW)
    assert promotion_blockers(summary(conn, rid, validation_protocol_passed=True)) == [
        "zero slippage: a strategy must survive realistic execution costs"
    ]


# ---- the explanation of every rupee is persisted with the trade -------------------------------------
from pathlib import Path  # noqa: E402

from algo.backtest.costs.policy import ScheduleCosts  # noqa: E402
from algo.backtest.costs.schedule import ScheduleBook, load_schedules  # noqa: E402
from algo.backtest.costs.slippage import SlippageModel  # noqa: E402

CFG_DIR = Path(__file__).parents[2] / "config/cost_schedules"


def sched_costs(slippage=None):
    book = ScheduleBook(load_schedules(CFG_DIR), allowed_statuses=("assumed_backfill",))
    return ScheduleCosts(book, slippage or SlippageModel(base_bps=D(5)))


def test_each_trade_persists_its_itemised_charges_with_the_exact_schedule(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    run_id = save_run(conn, run_backtest(conn, hold((a, 1)), cfg(cost=sched_costs())), NOW)
    cost, bps, charges = conn.execute(
        "SELECT cost, slippage_bps, charges FROM backtest_trade WHERE run_id=%s AND seq=1",
        (run_id,),
    ).fetchone()
    assert bps == D(5) and charges["schedule_id"] == "nse-cash-delivery-zerodha-assumed-2020-07-01"
    assert (
        charges["schedule_version"] == "2026-11-07.1"
        and charges["schedule_status"] == "assumed_backfill"
    )
    stt = next(ln for ln in charges["lines"] if ln["type"] == "STT")
    assert stt["formula"].startswith("0.1% of ") and stt["source"] == "zerodha_stt_delivery"
    assert stt["rounding"] == "HALF_UP_2DP" and D(stt["basis_value"]) > 0
    assert (
        sum(D(ln["amount"]) for ln in charges["lines"]) == cost
    )  # the lines add up to the trade cost


def test_the_ledger_fee_rows_match_the_persisted_trade_explanations_and_the_view(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    s = Scripted(HoldParams(ids=(a,), weights=(D(1),)), [{a: D(1)}, {}])
    r = run_backtest(conn, s, cfg(cost=sched_costs(SlippageModel(base_bps=D(5)))))
    run_id = save_run(conn, r, NOW)
    by_type = dict(
        conn.execute("SELECT fee_type, amount FROM backtest_ledger_fees WHERE run_id=%s", (run_id,))
    )
    assert (
        by_type == r.ledger.fee_breakdown() and "DP_CHARGE" in by_type and "STAMP_DUTY" in by_type
    )
    lines = conn.execute("SELECT charges FROM backtest_trade WHERE run_id=%s", (run_id,)).fetchall()
    explained = sum(D(ln["amount"]) for (c,) in lines for ln in c["lines"])
    notes = sum(D(n["amount"]) for n in r.note_charges)
    assert explained + notes == sum(by_type.values(), D(0))  # every rupee in the books is explained


def test_the_run_record_names_the_schedules_and_unverified_rates_block_promotion(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    rid = save_run(
        conn, run_backtest(conn, hold((a, 1)), cfg(mode=Mode.STRICT, cost=sched_costs())), NOW
    )
    used = conn.execute(
        "SELECT cost_model->'schedules_used' FROM backtest_run WHERE run_id=%s", (rid,)
    ).fetchone()[0]
    assert used[0]["status"] == "assumed_backfill"
    assert promotion_blockers(summary(conn, rid, validation_protocol_passed=True)) == [
        "cost schedules used are not verified (extracted or assumed rates)"
    ]
