from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from algo.backtest.costs.policy import CostModel
from algo.backtest.engine import InvalidTargets, run_backtest
from algo.data.review import resolve
from algo.strategy.base import Mode, Requirements, Strategy
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


class Peek(Strategy):
    """Records which instruments its strict/research window can see on each decision; scripted targets."""

    id, version, Params = "peek", "1", HoldParams

    def __init__(self, params, script=(), lookback=2):
        super().__init__(params)
        self.script, self.lookback, self.seen = list(script), lookback, []

    def universe(self, ctx):
        return list(self.params.ids)

    def requirements(self):
        return Requirements(lookback_days=self.lookback)

    def on_schedule(self, ctx):
        self.seen.append(
            (ctx.now().date(), set(ctx.data.history(list(self.params.ids), self.lookback)))
        )
        return self.script.pop(0) if self.script else None


def peek(a, b, script=(), lookback=2):
    return Peek(HoldParams(ids=(a, b), weights=(D(0), D(0))), script, lookback)


def test_strict_withholds_a_name_only_while_its_lookback_crosses_an_unresolved_action(env):
    # provisional (= unresolved in strict) demerger ex DAYS[6] = 10 Jun; 2-day lookback.
    conn, a, b = env
    put_bars(conn, a, flat(100))
    put_bars(conn, b, flat(50))
    provisional_demerger(conn, a, DAYS[6])
    s = peek(a, b)
    r = run_backtest(conn, s, cfg(mode=Mode.STRICT))
    seen = dict(s.seen)
    assert all(seen[d] == {a, b} for d in DAYS[:6])  # before the action is known: eligible
    assert seen[DAYS[6]] == {b} and seen[DAYS[7]] == {b}  # window still holds pre-ex-date bars
    assert seen[DAYS[8]] == {a, b}  # window 10..12 Jun no longer crosses: eligible again
    assert list(r.blocked) == [a]
    assert (
        "withheld on 2 decision day(s) 2025-06-10..2025-06-11" in r.blocked[a]
        and "demerger" in r.blocked[a]
    )
    research = peek(a, b)
    rr = run_backtest(conn, research, cfg(mode=Mode.RESEARCH))
    assert all(v == {a, b} for _, v in research.seen) and rr.blocked == {}


def test_strict_refuses_a_target_on_a_withheld_name_but_not_before_or_after(env):
    conn, a, b = env
    put_bars(conn, a, flat(100))
    put_bars(conn, b, flat(50))
    provisional_demerger(conn, a, DAYS[6])
    script = [None] * 6 + [{a: D(1)}]  # decides on DAYS[6]: a is withheld that day
    with pytest.raises(InvalidTargets, match="withheld"):
        run_backtest(conn, peek(a, b, script), cfg(mode=Mode.STRICT))
    after = run_backtest(conn, peek(a, b, [None] * 8 + [{a: D(1)}]), cfg(mode=Mode.STRICT))
    assert [(t.day, t.instrument_id, t.side) for t in after.trades] == [(DAYS[9], a, "BUY")]


def test_strict_holding_bought_before_the_action_is_frozen_while_withheld_and_flagged(env):
    conn, a, b = env
    put_bars(conn, a, flat(100))
    put_bars(conn, b, flat(50))
    provisional_demerger(conn, a, DAYS[6])
    # buy a on day 0's decision; on DAYS[6] and DAYS[7] the strategy (which cannot see a) asks for b only
    script = [{a: D(1)}] + [None] * 5 + [{b: D("0.5")}, {b: D("0.5")}]
    r = run_backtest(conn, peek(a, b, script), cfg(mode=Mode.STRICT))
    assert [(t.instrument_id, t.side) for t in r.trades][0] == (a, "BUY")
    assert all(
        not (t.instrument_id == a and t.side == "SELL") for t in r.trades
    )  # frozen, not force-sold
    assert [u["kind"] for u in r.unmodelled] == ["demerger"] and not r.accounting_complete


def test_strict_run_starting_after_the_ex_date_withholds_instead_of_failing(env):
    # the run starts after the action, but early lookbacks still reach back across it
    conn, a, b = env
    put_bars(conn, a, flat(100))
    put_bars(conn, b, flat(50))
    provisional_demerger(conn, a, DAYS[6])
    s = peek(a, b)
    r = run_backtest(conn, s, cfg(mode=Mode.STRICT, start=DAYS[7]))
    assert dict(s.seen) == {DAYS[7]: {b}, DAYS[8]: {a, b}}
    assert "2025-06-11..2025-06-11" in r.blocked[a]


def test_blocked_instrument_is_listed_with_its_reason(env):
    conn, a, b = env
    put_bars(conn, a, flat(100))
    put_bars(conn, b, flat(50))
    provisional_demerger(conn, a, DAYS[6])
    r = run_backtest(conn, Scripted(HoldParams(ids=(a, b), weights=(D(1), D(0))), [{b: D(1)}]),
                     cfg(mode=Mode.STRICT))  # fmt: skip
    assert list(r.blocked) == [a] and "demerger" in r.blocked[a]
    clean = run_backtest(conn, hold((b, 1)), cfg(mode=Mode.STRICT))
    assert clean.blocked == {} and clean.final_positions == {b: D(200)}


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


# ---- the financial ledger is the single source of truth -----------------------------------------
def assert_books_agree(r):
    assert r.reconciliation == [] and r.ledger_reconciled
    p = {k: D(v) for k, v in r.pnl.items()}
    assert abs(p["net"] - (r.equity[-1][1] - r.config.initial_cash)) <= D("1e-9")
    assert r.final_cash == r.ledger.cash and r.final_positions == r.ledger.quantities()


def test_realized_pnl_is_hand_computed_from_the_ledger(env):
    conn, a, _ = env
    put_bars(conn, a, {**flat(100, DAYS[:2]), **flat(110, DAYS[2:])})
    s = Scripted(HoldParams(ids=(a,), weights=(D(1),)), [{a: D(1)}, {}])  # buy, then exit
    r = run_backtest(conn, s, cfg())
    assert [(t.side, t.qty, t.price) for t in r.trades] == [
        ("BUY", D(100), D(100)),
        ("SELL", D(100), D(110)),
    ]
    assert r.pnl == {
        "realized": "1000",
        "unrealized": "0",
        "dividends": "0",
        "fees": "0",
        "net": "1000",
    }
    assert r.final_cash == D(11000) and r.final_positions == {}
    assert_books_agree(r)


def test_fees_and_unrealized_pnl_are_separated_and_the_identity_holds(env):
    conn, a, _ = env
    put_bars(conn, a, {**flat(100, DAYS[:5]), **flat(120, DAYS[5:])})
    r = run_backtest(conn, hold((a, 1)), cfg(cost=CostModel("t", D(10), D(5), False)))
    p = {k: D(v) for k, v in r.pnl.items()}
    assert p["fees"] == sum((t.cost for t in r.trades), D(0)) > 0
    assert p["realized"] == 0 and p["unrealized"] > 0  # still holding: gain is unrealized
    assert p["net"] == p["unrealized"] - p["fees"]
    assert_books_agree(r)


def test_every_trade_and_action_is_traceable_in_the_ledger(env):
    conn, a, _ = env
    put_bars(conn, a, {**flat(100, DAYS[:4]), **flat(50, DAYS[4:])})
    add_action(conn, a, DAYS[4], "bonus", num=D(2), den=D(1))
    add_action(conn, a, DAYS[6], "dividend", amount=D(1))
    r = run_backtest(conn, hold((a, 1)), cfg(cost=CostModel("t", D(10), D(0), False)))
    refs = {e.ref for e in r.ledger.entries}
    assert len(r.trades) > 1  # the bonus and the dividend cash trigger rebalancing trades
    assert refs == {
        "initial",
        *(f"trade:{t.seq}" for t in r.trades),  # every trade is in the ledger, and nothing else is
        f"action:{a}:{DAYS[4]}:bonus:0",
        f"action:{a}:{DAYS[6]}:dividend:1",
    }
    buy = [(e.ledger, e.kind) for e in r.ledger.entries if e.ref == "trade:1"]
    assert sorted(buy) == [
        ("cash", "BUY"),
        ("cash", "FEE"),
        ("fee", "COMMISSION"),
        ("position", "BUY"),
    ]
    split = next(e for e in r.ledger.entries if e.kind == "SPLIT")
    assert split.qty == r.trades[0].qty and split.amount == 0  # share count doubles, cost unchanged
    assert r.dividends_received == sum(e.amount for e in r.ledger.entries if e.kind == "DIVIDEND")
    assert_books_agree(r)


def test_held_through_an_unmodellable_action_is_flagged_in_the_ledger_not_hidden(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    provisional_demerger(conn, a, DAYS[6])
    r = run_backtest(conn, hold((a, 1)), cfg())
    (e,) = r.ledger.unmodelled()
    assert (e.kind, e.instrument_id, e.qty) == ("UNMODELLED:resolved", a, D(100))
    assert e.ref == f"action:{a}:{DAYS[6]}:resolved:0" and r.reconciliation == []
    assert not r.accounting_complete


def test_a_corrupted_ledger_is_reported_on_the_run(env):
    from dataclasses import replace

    conn, a, _ = env
    put_bars(conn, a, flat(100))
    r = run_backtest(conn, hold((a, 1)), cfg())
    r.ledger.entries[1] = replace(r.ledger.entries[1], amount=r.ledger.entries[1].amount + D(1))
    assert r.ledger.reconcile({a: D(100)}) != []


def test_ledger_changes_change_the_result_hash(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    r = run_backtest(conn, hold((a, 1)), cfg())
    h = r.result_hash
    r.ledger.entries[0] = type(r.ledger.entries[0])(
        1, DAYS[0], "cash", "INITIAL", None, D(0), D(9999), "initial"
    )
    assert r.result_hash != h


@pytest.mark.parametrize("seed", range(12))
def test_books_agree_on_random_price_paths_and_random_targets(env, seed):
    """Fuzz: seeded random walks, random daily targets, costs on. The ledger must always reconcile,
    never overspend, and net P&L must equal the change in equity."""
    import random

    conn, a, b = env
    rng = random.Random(seed)
    for iid in (a, b):
        price = D(rng.randint(20, 400))
        bars = {}
        for d in DAYS:
            price = max(D(1), price + D(rng.randint(-15, 15)))
            bars[d] = (price, price + D(rng.randint(-5, 5)) if price > 6 else price)
        put_bars(conn, iid, bars, vol=rng.choice([50, 400, 10_000_000]))
    script = []
    for _ in range(9):
        wa = D(rng.randint(0, 10)) / 10
        wb = D(rng.randint(0, 10)) / 10
        if wa + wb > 1:
            wb = 1 - wa
        script.append(rng.choice([None, {a: wa, b: wb}, {a: wa}, {}]))
    s = Scripted(HoldParams(ids=(a, b), weights=(D(1), D(0))), script)
    r = run_backtest(
        conn, s, cfg(cost=CostModel("t", D(10), D(5), False), max_participation=D("0.5"))
    )
    assert_books_agree(r)
    assert r.ledger.cash >= 0 and all(q > 0 for q in r.final_positions.values())
    assert len(r.equity) == 10


# ---- schedule-based costs: every rupee explained --------------------------------------------------
from pathlib import Path  # noqa: E402

from algo.backtest.costs.policy import ScheduleCosts  # noqa: E402
from algo.backtest.costs.schedule import NoScheduleForDate, ScheduleBook, load_schedules  # noqa: E402
from algo.backtest.costs.slippage import SlippageModel  # noqa: E402

CFG_DIR = (
    Path(__file__).parents[1] / "fixtures/cost_schedules"
)  # a frozen copy: these tests exercise mechanics, not today's rates


def sched(slippage=None, statuses=("assumed_backfill",)):
    book = ScheduleBook(load_schedules(CFG_DIR), allowed_statuses=statuses)
    return ScheduleCosts(book, slippage or SlippageModel())


def test_a_delivery_buy_with_real_schedule_costs_is_hand_computed_to_the_paisa(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    r = run_backtest(conn, hold((a, 1)), cfg(cost=sched()))
    # 100 shares would cost 10,011.88 all-in (> Rs 10,000), so the engine buys 99:
    #   STT 9.90 + exchange 0.30 + SEBI 0.01 + stamp 1.49 + GST 18% x (0 + 0.30 + 0.01) = 0.06
    (t,) = r.trades
    assert (t.qty, t.price, t.cost, t.slippage_bps) == (D(99), D(100), D("11.76"), D(0))
    assert {ln.type: ln.amount for ln in t.charges.lines} == {
        "BROKERAGE": D("0.00"), "STT": D("9.90"), "EXCHANGE_TRANSACTION": D("0.30"),
        "SEBI_TURNOVER": D("0.01"), "STAMP_DUTY": D("1.49"), "GST": D("0.06"),
    }  # fmt: skip
    # the delivery contract note carries a Rs 0.01 minimum brokerage, posted once for the day
    assert r.note_charges == [{"day": str(DAYS[1]), "type": "BROKERAGE", "amount": "0.01"}]
    assert r.ledger.fee_breakdown() == {
        "BROKERAGE": D("0.01"), "EXCHANGE_TRANSACTION": D("0.30"), "GST": D("0.06"),
        "SEBI_TURNOVER": D("0.01"), "STAMP_DUTY": D("1.49"), "STT": D("9.90"),
    }  # fmt: skip
    assert r.final_cash == D(10000) - D(9900) - D("11.76") - D("0.01") == D("88.23")
    assert D(r.pnl["fees"]) == D("11.77") and D(r.pnl["net"]) == D("-11.77")
    assert r.reconciliation == []


def test_a_round_trip_with_the_dp_charge_reconciles_to_the_rupee(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    s = Scripted(HoldParams(ids=(a,), weights=(D(1),)), [{a: D(1)}, {}])
    r = run_backtest(conn, s, cfg(cost=sched()))
    buy, sell = r.trades
    # SELL 99 @ 100: STT 9.90 + exchange 0.30 + SEBI 0.01 + DP 15.34 (GST included) + GST 0.06 = 25.61
    assert sell.cost == D("25.61") and sell.charges.amount("DP_CHARGE") == D("15.34")
    assert sell.charges.amount("STAMP_DUTY") == 0  # stamp duty is buyer-side only
    assert [n["day"] for n in r.note_charges] == [str(DAYS[1]), str(DAYS[2])]  # one note a day
    assert D(r.pnl["fees"]) == D("11.76") + D("25.61") + D("0.01") + D("0.01")
    assert r.final_cash == D(10000) - D("11.77") - D("25.62") and r.final_positions == {}
    assert D(r.pnl["net"]) == D("-37.39") == r.equity[-1][1] - D(10000)
    assert sum((t.cost for t in r.trades), D(0)) + D("0.02") == D(r.pnl["fees"])  # trades + notes
    assert r.reconciliation == []


def test_slippage_moves_the_fill_price_and_is_recorded_on_the_trade(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    s = Scripted(HoldParams(ids=(a,), weights=(D(1),)), [{a: D(1)}, {}])
    r = run_backtest(conn, s, cfg(cost=sched(SlippageModel(base_bps=D(10)))))
    buy, sell = r.trades
    assert (buy.price, buy.slippage_bps) == (D("100.10"), D(10))
    assert (sell.price, sell.slippage_bps) == (D("99.90"), D(10))
    assert buy.qty == D(99)  # 100 x 100.10 + charges would exceed the cash
    assert D(r.pnl["realized"]) == D(99) * (
        D("99.90") - D("100.10")
    )  # -19.8: the slippage round trip


def test_slippage_grows_with_the_orders_share_of_the_bars_volume(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100), vol=400)  # cap = 5% of 400 = 20 shares = 5% participation
    r = run_backtest(
        conn, hold((a, 1)), cfg(cost=sched(SlippageModel(participation_bps_per_pct=D(2))))
    )
    assert r.trades[0].qty == 20 and r.trades[0].slippage_bps == D(10)  # 5% x 2 bps per 1%
    assert r.trades[0].price == D("100.10")


def test_volatility_and_illiquidity_use_only_sessions_before_the_execution_bar(env):
    conn, a, _ = env
    put_bars(conn, a, {d: (D(100), D(100)) for d in DAYS})
    conn.execute(
        "UPDATE bar_1d SET high=104, low=98 WHERE ts < %s", (datetime(2025, 6, 3, tzinfo=UTC),)
    )
    m = SlippageModel(
        volatility_fraction=D("0.5"), illiquid_adv_threshold=D(10**12), illiquid_extra_bps=D(7)
    )
    r = run_backtest(conn, hold((a, 1)), cfg(cost=sched(m)))
    # only the prior session (2 Jun) has a wide range: (104-98)/100 = 600 bps -> 0.5 x 600 = 300; +7
    # illiquid. The execution bar (3 Jun) is flat: if its own range leaked in, this would be 7, not 307.
    assert r.trades[0].slippage_bps == D(307)
    # the execution bar's own range never feeds the estimate (that would be look-ahead)


def test_no_schedule_for_the_trade_date_stops_the_run(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    with pytest.raises(NoScheduleForDate, match="statuses allowed: verified"):
        run_backtest(conn, hold((a, 1)), cfg(cost=sched(statuses=("verified",))))
    with pytest.raises(NoScheduleForDate):  # the current schedule starts 2026-03-01
        run_backtest(conn, hold((a, 1)), cfg(cost=sched(statuses=("extracted_unverified",))))


def test_the_run_records_which_schedules_it_used_and_that_they_are_unverified(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    r = run_backtest(conn, hold((a, 1)), cfg(cost=sched()))
    assert r.cost_info["schedules_used"] == [
        {
            "id": "nse-cash-delivery-zerodha-assumed-2020-07-01",
            "version": "2026-11-07.1",
            "status": "assumed_backfill",
        }
    ]
    assert r.cost_info["unverified_schedules"] is True and r.cost_info["placeholder"] is False
    assert r.cost_info["kind"] == "schedule" and r.cost_info["zero_slippage"] is True


def test_the_flat_placeholder_still_works_and_is_marked_as_such(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    r = run_backtest(conn, hold((a, 1)), cfg(cost=CostModel("t", D(10), D(5), True)))
    assert r.cost_info["kind"] == "flat_bps" and r.cost_info["placeholder"] is True
    assert r.cost_info["schedules_used"] == [{"id": "t", "version": "1", "status": "placeholder"}]
    assert r.cost_info["unverified_schedules"] is False and r.note_charges == []


def test_an_instruments_very_first_bar_has_no_history_so_volatility_and_liquidity_are_unknown(env):
    """B first trades on the day the order executes: no prior sessions exist to estimate from."""
    conn, a, b = env
    put_bars(conn, a, flat(100))
    put_bars(conn, b, flat(100, DAYS[1:]))
    m = SlippageModel(
        volatility_fraction=D(1), illiquid_adv_threshold=D(1), illiquid_extra_bps=D(9)
    )
    s = Scripted(HoldParams(ids=(a, b), weights=(D(1), D(0))), [{b: D(1)}])
    r = run_backtest(conn, s, cfg(cost=sched(m)))
    (t,) = r.trades
    assert t.instrument_id == b and t.day == DAYS[1]
    assert t.slippage_bps == D(
        9
    )  # range unknown => 0 bps; liquidity unknown => treated as illiquid


def scripted(a, *targets):
    return Scripted(HoldParams(ids=(a,), weights=(D(1),)), [{a: D(w)} for w in targets])


def test_a_maximum_order_value_splits_a_big_order_over_several_days(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    r = run_backtest(conn, hold((a, 1)), cfg(max_order_value=D(2000)))
    assert [(t.day.day, t.qty) for t in r.trades] == [(3, 20), (4, 20), (5, 20), (6, 20), (9, 20)]
    assert r.final_positions == {a: D(100)}


def test_orders_below_the_minimum_order_value_are_not_placed(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    r = run_backtest(conn, scripted(a, 1, "0.95"), cfg(min_order_value=D(1000)))
    assert [(t.side, t.qty) for t in r.trades] == [
        ("BUY", D(100))
    ]  # the 5-share trim (500) is skipped
    r = run_backtest(conn, scripted(a, "0.05"), cfg(min_order_value=D(1000)))
    assert r.trades == [] and r.final_cash == D(10000)  # a 500 opening buy is too small


def test_a_sale_that_closes_the_whole_position_is_allowed_below_the_minimum(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    r = run_backtest(conn, scripted(a, 1, "0.05", 0), cfg(min_order_value=D(1000)))
    assert [(t.side, t.qty) for t in r.trades] == [("BUY", D(100)), ("SELL", D(95)), ("SELL", D(5))]
    assert r.final_positions == {}


def test_order_size_limits_default_to_off_and_must_be_consistent():
    assert cfg().min_order_value == 0 and cfg().max_order_value is None
    with pytest.raises(ValueError, match="maximum"):
        cfg(min_order_value=D(5000), max_order_value=D(1000))
    with pytest.raises(ValueError, match="negative"):
        cfg(min_order_value=D(-1))


def test_progress_is_reported_for_every_day_with_the_total(env):
    conn, a, _ = env
    put_bars(conn, a, flat(100))
    seen = []
    r = run_backtest(conn, hold((a, 1)), cfg(), on_day=lambda i, n, d: seen.append((i, n, d)))
    assert [(i, n) for i, n, _ in seen] == [(k, len(r.equity)) for k in range(1, len(r.equity) + 1)]
    assert [d for _, _, d in seen] == [d for d, _ in r.equity]
    quiet = run_backtest(conn, hold((a, 1)), cfg())
    assert quiet.result_hash == r.result_hash  # watching progress changes nothing
