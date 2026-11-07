from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from algo.backtest.engine import CostModel, InvalidTargets, run_backtest
from algo.data.review import resolve
from algo.strategy.base import Mode, Strategy
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
from tests.support.strategies import HoldParams, Scripted

pytestmark = pytest.mark.integration


@pytest.fixture
def env(conn):
    return make_env(conn)


def test_buy_and_hold_hand_computed_zero_costs(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    r = run_backtest(conn, hold((a, 1)), cfg())
    assert [(t.day, t.side, t.qty, t.price) for t in r.trades] == [(DAYS[1], "BUY", D(100), D(100))]
    assert r.final_positions == {a: D(100)} and r.final_cash == 0
    assert len(r.equity) == 10 and {v for _, v in r.equity} == {D(10000)}
    assert r.accounting_complete and r.metrics["total_return"] == 0


def test_two_instruments_are_sized_by_weight_at_the_open(env):
    conn, a, b = env
    put_bars(conn, a, flat(100))
    put_bars(conn, b, flat(50))
    r = run_backtest(conn, hold((a, "0.5"), (b, "0.5")), cfg())
    assert r.final_positions == {a: D(50), b: D(100)} and r.final_cash == 0


def test_costs_slippage_and_commission_hand_computed(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    r = run_backtest(conn, hold((a, 1)), cfg(cost=CostModel("t", D(10), D(5), False)))
    (t,) = r.trades
    # fill 100 * 1.0005 = 100.05 ; affordable = floor(10000 / (100.05 * 1.001)) = 99
    assert (t.qty, t.price, t.cost) == (D(99), D("100.05"), D("9.90495"))
    assert r.final_cash == D(10000) - D("9904.95") - D("9.90495") == D("85.14505")


def test_fills_are_capped_at_a_share_of_bar_volume_and_the_rest_cancels_then_retries(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100), vol=400)  # 5% of 400 = 20 shares a day
    r = run_backtest(conn, hold((a, 1)), cfg())
    assert [(t.day.day, t.qty) for t in r.trades] == [(3, 20), (4, 20), (5, 20), (6, 20), (9, 20)]
    assert r.final_positions == {a: D(100)}


def test_cash_never_goes_negative_with_costs_and_full_investment(env):
    conn, a, b = env
    put_bars(conn, a, {d: D(100 + i) for i, d in enumerate(DAYS)})
    put_bars(conn, b, {d: D(37 + i) for i, d in enumerate(DAYS)})
    r = run_backtest(
        conn, hold((a, "0.5"), (b, "0.5")), cfg(cost=CostModel("t", D(10), D(5), False))
    )
    assert r.final_cash >= 0


def test_execution_and_accounting_use_raw_prices_across_a_bonus(env):
    conn, a, _ = env
    put_bars(conn, a, {**flat(100, DAYS[:4]), **flat(50, DAYS[4:])})  # 1:1 bonus, ex Fri 6 Jun
    add_action(conn, a, DAYS[4], "bonus", num=D(2), den=D(1))
    r = run_backtest(conn, hold((a, 1)), cfg())
    (t,) = r.trades
    assert t.price == D(100)  # filled at the RAW open, not the adjusted 50
    assert r.final_positions == {a: D(200)} and r.final_cash == 0  # shares doubled by the bonus
    assert {v for _, v in r.equity} == {D(10000)}  # no jump at the ex-date
    assert r.accounting_complete


def test_cash_dividends_are_credited_on_the_ex_date(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    add_action(conn, a, DAYS[5], "dividend", amount=D(2))
    r = run_backtest(conn, hold((a, 1)), cfg())
    assert r.dividends_received == D(200)  # 100 shares x Rs 2
    assert dict(r.equity)[DAYS[5]] == D(10200)


def test_a_missing_bar_means_no_trade_and_the_last_close_is_used(env):
    conn, a, b = env
    put_bars(conn, a, flat(100))
    put_bars(conn, b, flat(50, [d for d in DAYS if d != DAYS[3]]))
    r = run_backtest(conn, hold((a, "0.5"), (b, "0.5")), cfg())
    assert all(not (t.instrument_id == b and t.day == DAYS[3]) for t in r.trades)
    assert dict(r.equity)[DAYS[3]] == D(10000)  # marked at BBB's previous close


# ---- no look-ahead -------------------------------------------------------------------------------
def test_the_strategy_only_ever_sees_bars_that_have_closed_and_been_published(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    s = hold((a, 1))
    run_backtest(conn, s, cfg())
    assert len(s.seen) == 9  # no decision on the final day (it could never execute)
    for now, last_bar in s.seen:
        assert last_bar[a] == datetime(now.year, now.month, now.day, 3, 45, tzinfo=UTC)  # today's
        assert now == datetime(now.year, now.month, now.day, 13, 0, tzinfo=UTC)  # 09:15 IST + 9h15


class Momentum(Strategy):
    id, version, Params = "mom", "1", HoldParams

    def universe(self, ctx):
        return list(self.params.ids)

    def on_schedule(self, ctx):
        (bars,) = ctx.data.history(self.params.ids, 30).values()
        return {self.params.ids[0]: D(1) if bars[-1].close > bars[0].close else D(0)}


def test_results_up_to_T_do_not_change_when_the_future_is_added(env):
    """Look-ahead harness: a run that stops at T must equal the prefix of a run that goes on."""
    conn, a, _ = env
    put_bars(
        conn,
        a,
        {
            d: D(p)
            for d, p in zip(DAYS, (100, 101, 99, 102, 104, 103, 105, 107, 106, 108), strict=True)
        },
    )
    p = HoldParams(ids=(a,), weights=(D(1),))
    short = run_backtest(conn, Momentum(p), cfg(end=DAYS[5]))
    long = run_backtest(conn, Momentum(p), cfg(end=DAYS[9]))
    assert short.equity == long.equity[: len(short.equity)]
    assert short.trades == [t for t in long.trades if t.day <= DAYS[5]]
    assert short.trades  # the comparison is not vacuous


# ---- strategy output validation -------------------------------------------------------------------
@pytest.mark.parametrize("case", ["unknown_instrument", "negative", "sum_over_100", "over_max"])
def test_invalid_targets_abort_the_run(env, case):
    conn, a, b = env
    put_bars(conn, a, flat(100))
    put_bars(conn, b, flat(50))
    bad = {
        "unknown_instrument": {999999: D(1)},
        "negative": {a: D(-1)},
        "sum_over_100": {a: D("0.7"), b: D("0.4")},
        "over_max": {a: D("1.5")},
    }[case]
    s = Scripted(HoldParams(ids=(a, b), weights=(D(1), D(0))), [bad])
    with pytest.raises(InvalidTargets):
        run_backtest(conn, s, cfg())


def test_max_weight_is_enforced(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    s = Scripted(HoldParams(ids=(a,), weights=(D(1),)), [{a: D("0.6")}])
    with pytest.raises(InvalidTargets, match="max_weight"):
        run_backtest(conn, s, cfg(max_weight=D("0.5")))


def test_none_keeps_the_previous_targets_and_places_no_new_orders(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    s = Scripted(HoldParams(ids=(a,), weights=(D(1),)), [{a: D(1)}])  # then None forever
    r = run_backtest(conn, s, cfg())
    assert len(r.trades) == 1 and s.calls == 9 and r.final_positions == {a: D(100)}


# ---- reader modes, provisional/unapplied/unmodelled reporting ------------------------------------
def test_research_mode_applies_provisional_estimates_and_reports_them(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    provisional_demerger(conn, a, DAYS[6])
    r = run_backtest(conn, hold((a, 1)), cfg(mode=Mode.RESEARCH))
    assert [(e["kind"], e["factor"]) for e in r.provisional] == [("resolved", "0.9")]
    assert r.unapplied == [] and r.blocked == {} and a in r.adjustment_versions


def test_strict_mode_blocks_instruments_with_provisional_actions_and_records_why(env):
    conn, a, b = env
    put_bars(conn, a, flat(100))
    put_bars(conn, b, flat(50))
    provisional_demerger(conn, a, DAYS[6])
    r = run_backtest(conn, hold((b, 1)), cfg(mode=Mode.STRICT))  # b is clean
    assert r.final_positions == {b: D(200)}
    s = Scripted(HoldParams(ids=(a, b), weights=(D(1), D(0))), [{a: D(1)}])
    blocked_run = None
    with pytest.raises(InvalidTargets, match="unblocked"):
        blocked_run = run_backtest(conn, s, cfg(mode=Mode.STRICT))
    assert blocked_run is None
    both = run_backtest(conn, hold((b, 1)), cfg(mode=Mode.STRICT, start=DAYS[0]))
    assert both.blocked == {}


def test_blocked_instrument_is_listed_with_its_reason(env):
    conn, a, b = env
    put_bars(conn, a, flat(100))
    put_bars(conn, b, flat(50))
    provisional_demerger(conn, a, DAYS[6])
    r = run_backtest(conn, Scripted(HoldParams(ids=(a, b), weights=(D(1), D(0))), [{b: D(1)}]),
                     cfg(mode=Mode.STRICT))  # fmt: skip
    assert list(r.blocked) == [a] and "demerger" in r.blocked[a]


def test_instrument_without_bars_in_range_is_blocked(env):
    conn, a, b = env
    put_bars(conn, a, flat(100))
    r = run_backtest(
        conn, Scripted(HoldParams(ids=(a, b), weights=(D(1), D(0))), [{a: D(1)}]), cfg()
    )
    assert r.blocked == {b: "no bars in range"}


def test_unpriced_actions_are_reported_separately_from_provisional(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    add_action(conn, a, DAYS[6], "rights", status="review", subject="Rights 1:15 @ Premium Rs 1247")
    r = run_backtest(conn, hold((a, 1)), cfg(mode=Mode.RESEARCH))
    assert [e["kind"] for e in r.unapplied] == ["rights"] and r.provisional == []


def test_holding_through_an_unmodellable_action_makes_the_accounting_incomplete(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    provisional_demerger(conn, a, DAYS[6])
    r = run_backtest(conn, hold((a, 1)), cfg(mode=Mode.RESEARCH))
    assert not r.accounting_complete
    assert [(e["kind"], e["ex_date"], e["qty"]) for e in r.unmodelled] == [
        ("resolved", "2025-06-10", "100")
    ]


def test_an_action_on_a_name_we_do_not_hold_is_not_an_accounting_problem(env):
    conn, a, b = env
    put_bars(conn, a, flat(100))
    put_bars(conn, b, flat(50))
    provisional_demerger(conn, a, DAYS[6])
    r = run_backtest(conn, hold((b, 1)), cfg(mode=Mode.RESEARCH))
    assert r.accounting_complete


# ---- reproducibility, persistence, promotion ------------------------------------------------------
def test_same_inputs_give_the_same_hash_and_any_change_gives_a_different_one(env):
    conn, a, _ = env
    put_bars(
        conn,
        a,
        {
            d: D(p)
            for d, p in zip(DAYS, (100, 101, 99, 102, 104, 103, 105, 107, 106, 108), strict=True)
        },
    )
    first = run_backtest(conn, hold((a, 1)), cfg())
    assert first.result_hash == run_backtest(conn, hold((a, 1)), cfg()).result_hash
    assert first.result_hash != run_backtest(conn, hold((a, "0.5")), cfg()).result_hash
    costly = run_backtest(conn, hold((a, 1)), cfg(cost=CostModel("t", D(10), D(5), False)))
    assert first.result_hash != costly.result_hash


def test_adjustment_version_changes_when_a_provisional_factor_changes(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    provisional_demerger(conn, a, DAYS[6])
    v1 = run_backtest(conn, hold((a, 1)), cfg()).adjustment_versions[a]
    resolve(conn, symbol="AAA", ex_date=DAYS[6], kind="demerger", method="direct",
            params={"factor": D("0.8")}, note="n", by="t", now=NOW)  # fmt: skip
    assert run_backtest(conn, hold((a, 1)), cfg()).adjustment_versions[a] != v1


def test_an_order_that_rounds_to_zero_shares_is_skipped_not_traded(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100), vol=10)  # 5% of 10 shares = 0.5 -> 0 whole shares
    r = run_backtest(conn, hold((a, 1)), cfg())
    assert r.trades == [] and r.final_cash == D(10000)


def test_cash_limits_a_buy_when_the_target_is_not_affordable(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    r = run_backtest(conn, hold((a, 1)), cfg(initial_cash=D(250)))
    assert r.final_positions == {a: D(2)} and r.final_cash == D(50)  # floor(250/100)
