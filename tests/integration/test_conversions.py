"""The explicit ISIN-change conversion, end to end: the instruction table, its loader, and a backtest whose
position is HELD ACROSS the change. Synthetic data only: the real NESTLEIND history has no such position
and none is manufactured.

Calendar: old ISIN trades 27 Dec .. 4 Jan; the new ISIN's first session is 5 Jan (10:1 split ex-date, the
same economic event as the conversion). Closes are chosen so wealth is continuous across the change:
old 20,100 on 4 Jan = new 2,010 on 5 Jan."""

from datetime import UTC, date, datetime
from decimal import Decimal as D

import psycopg
import pytest

from algo.backtest.engine import run_backtest
from algo.data.conversions import (
    ConversionRecordError,
    conversion_ref,
    load_conversions,
    store_conversion,
)
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from tests.support.bt import add_action, cfg, put_bars
from tests.support.strategies import HoldParams, Scripted

pytestmark = pytest.mark.integration
CHANGE = date(2024, 1, 5)
OLD_DAYS = [
    date(2023, 12, 27), date(2023, 12, 28), date(2023, 12, 29),
    date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4),
]  # fmt: skip
NEW_DAYS = [CHANGE, date(2024, 1, 8), date(2024, 1, 9)]
ALL_DAYS = OLD_DAYS + NEW_DAYS


def add_conversion(
    conn, old, new, status="VERIFIED", absorbs=True, evidence='["NSE circular CML60084"]'
):
    conn.execute(
        "INSERT INTO security_conversion (source_instrument_id, target_instrument_id, effective_date,"
        " last_source_session, ratio_num, ratio_den, absorbs_ex_date, absorbs_kind, evidence,"
        " verification_status, recorded_at) VALUES (%s,%s,%s,'2024-01-04',10,1,%s,%s,%s::jsonb,%s, now())",
        (
            old,
            new,
            CHANGE,
            CHANGE if absorbs else None,
            "split" if absorbs else None,
            evidence,
            status,
        ),
    )


@pytest.fixture
def world(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    old, new, other = (repo.add_instrument(x, s) for s in ("NESTLE-OLD", "NESTLEIND", "AAA"))
    put_bars(conn, old, {d: D(20000) if d != OLD_DAYS[-1] else D(20100) for d in OLD_DAYS})
    put_bars(conn, new, {CHANGE: D(2010), NEW_DAYS[1]: D(2020), NEW_DAYS[2]: D(2020)})
    put_bars(conn, other, {d: D(100) for d in ALL_DAYS})
    add_action(conn, new, CHANGE, "split", num=D(10), den=D(1))
    conn.execute(
        "INSERT INTO corporate_action_relationship (relationship_type, source_instrument_id,"
        " target_instrument_id, target_symbol, effective_date, evidence, review_decision_id, recorded_at)"
        " VALUES ('SAME_ISSUER_ISIN_CHANGE', %s, %s, 'NESTLEIND', %s, '[\"circular\"]'::jsonb, 15, now())",
        (old, new, CHANGE),
    )
    return conn, old, new, other


def hold_old(world, universe=None):
    conn, old, new, other = world
    ids = universe or (old, new, other)
    strat = Scripted(HoldParams(ids=ids, weights=tuple(D(0) for _ in ids)), [{old: D(1)}])
    return run_backtest(
        conn, strat, cfg(start=ALL_DAYS[0], end=ALL_DAYS[-1], initial_cash=D(100000))
    )


def test_a_position_held_across_the_isin_change_converts_with_cost_and_wealth_intact(world):
    conn, conv_old, conv_new, _ = world
    add_conversion(conn, conv_old, conv_new)
    res = hold_old(world)
    led = res.ledger
    assert [t.instrument_id for t in res.trades] == [
        conv_old
    ]  # one purchase; the conversion is NOT a trade
    assert res.final_positions == {
        conv_new: D(50)
    }  # 5 old shares x 10; the same-day split was not applied twice
    assert (led.cost_basis(conv_old), led.cost_basis(conv_new)) == (
        D(0),
        D(100000),
    )  # cost moved exactly
    equity = dict(res.equity)
    assert (
        equity[date(2024, 1, 4)] == equity[CHANGE] == D(100500)
    )  # no jump: the same wealth on the new scale
    assert res.pnl["realized"] == "0" and res.pnl["fees"] == "0"
    assert res.ledger_reconciled and res.accounting_complete and res.unmodelled == []
    (c,) = res.conversions
    assert (c["ref"], c["day"], c["qty_out"], c["qty_in"], c["cost"]) == (
        conversion_ref(conv_old, conv_new, CHANGE), "2024-01-05", "5", "50", "100000",
    )  # fmt: skip
    kinds = [(e.ledger, e.kind) for e in led.entries if e.ref == c["ref"]]
    assert kinds == [
        ("position", "CONVERT_OUT"),
        ("position", "CONVERT_IN"),
    ]  # no cash, fee or P&L entry


def test_without_a_verified_instruction_the_held_position_is_flagged_not_guessed(world):
    conn, old, new, _ = world
    for status in (None, "PROVISIONAL", "REJECTED"):
        conn.execute("DELETE FROM security_conversion")
        if status:
            add_conversion(conn, old, new, status=status)
        res = hold_old(world)
        assert res.final_positions == {
            old: D(5)
        }  # nothing converted: an ISIN change is never inferred
        assert [(u["instrument_id"], u["kind"]) for u in res.unmodelled] == [(old, "ISIN_CHANGE")]
        assert not res.accounting_complete


def test_a_verified_instruction_whose_target_is_outside_the_run_is_flagged_too(world):
    conn, old, new, other = world
    add_conversion(conn, old, new)
    res = hold_old(world, universe=(old, other))  # the new ISIN is not in this run's universe
    assert res.final_positions == {old: D(5)}
    assert [(u["instrument_id"], u["kind"]) for u in res.unmodelled] == [(old, "ISIN_CHANGE")]


def test_a_run_that_never_held_the_old_isin_converts_and_flags_nothing(world):
    conn, old, new, other = world
    add_conversion(conn, old, new)
    strat = Scripted(HoldParams(ids=(old, new, other), weights=(D(0), D(0), D(0))), [{other: D(1)}])
    res = run_backtest(
        conn, strat, cfg(start=ALL_DAYS[0], end=ALL_DAYS[-1], initial_cash=D(100000))
    )
    assert res.conversions == [] and res.unmodelled == [] and set(res.final_positions) == {other}


def test_the_loader_returns_only_verified_instructions_with_their_absorbed_action(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    a, b, c = (repo.add_instrument(x, s) for s in ("A", "B", "C"))
    add_conversion(conn, a, b)
    add_conversion(conn, b, c, status="PROVISIONAL", absorbs=False)
    add_conversion(conn, a, c, absorbs=False)
    got = load_conversions(conn)
    assert [(g.source, g.target, g.verified) for g in got] == [(a, b, True), (a, c, True)]
    assert got[0].absorbs == (CHANGE, "split") and got[1].absorbs is None
    assert got[0].evidence == ("NSE circular CML60084",) and (got[0].num, got[0].den) == (
        D(10),
        D(1),
    )
    assert got[0].ref == conversion_ref(a, b, CHANGE) == f"convert:{a}:{b}:2024-01-05"
    conn.execute("DROP TABLE security_conversion")  # a database before migration 025
    assert load_conversions(conn) == []


def test_the_instruction_table_refuses_malformed_instructions(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    a, b = (repo.add_instrument(x, s) for s in ("A", "B"))
    for kw in (
        dict(evidence="[]"),  # no evidence
        dict(evidence='"text"'),  # evidence must be an array
        dict(status="GUESSED"),
    ):
        with pytest.raises(psycopg.errors.CheckViolation):
            add_conversion(conn, a, b, **kw)
    with pytest.raises(psycopg.errors.CheckViolation):
        add_conversion(conn, a, a)  # a security does not convert into itself
    add_conversion(conn, a, b)
    with pytest.raises(psycopg.errors.UniqueViolation):
        add_conversion(conn, a, b)
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO security_conversion (source_instrument_id, target_instrument_id, effective_date,"
            " ratio_num, ratio_den, absorbs_ex_date, evidence, recorded_at)"
            " VALUES (%s,%s,'2024-02-01',1,1,'2024-02-01','[\"e\"]'::jsonb, now())",
            (b, a),
        )  # an absorbed date without its kind


def test_a_run_that_touches_neither_isin_ignores_the_link_and_one_with_only_the_new_isin_is_unaffected(
    world,
):
    conn, old, new, other = world
    add_conversion(conn, old, new)
    for universe in (
        (other,),
        (new, other),
    ):  # neither ISIN / only the new ISIN: no position to convert or flag
        strat = Scripted(
            HoldParams(ids=universe, weights=tuple(D(0) for _ in universe)), [{other: D(1)}]
        )
        res = run_backtest(
            conn, strat, cfg(start=ALL_DAYS[0], end=ALL_DAYS[-1], initial_cash=D(100000))
        )
        assert (
            res.conversions == [] and res.unmodelled == [] and set(res.final_positions) == {other}
        )
    conn.execute("DELETE FROM security_conversion")  # only the new ISIN, and no instruction at all
    strat = Scripted(HoldParams(ids=(new, other), weights=(D(0), D(0))), [{new: D(1)}])
    res = run_backtest(
        conn, strat, cfg(start=ALL_DAYS[0], end=ALL_DAYS[-1], initial_cash=D(100000))
    )
    # nothing held in the source: nothing to flag; the single target is dropped because the new ISIN
    # has no session on the day it is first executed (it is not tradable before its own first bar)
    assert res.unmodelled == [] and res.final_positions == {} and res.trades == []


DOC = {
    "source_isin": "INE239A01016", "target_isin": "INE239A01024", "effective_date": "2024-01-05",
    "last_source_session": "2024-01-04", "ratio_num": 10, "ratio_den": 1,
    "absorbs": {"ex_date": "2024-01-05", "kind": "split"},
    "evidence": ["NSE circular CML60084", "NSE circular FAOP59844"],
    "verification_status": "VERIFIED", "review_decision_id": 15,
}  # fmt: skip
NOW = datetime(2026, 11, 9, tzinfo=UTC)


def test_a_reviewed_instruction_is_recorded_once_by_isin_and_linked_to_the_identity_relationship(
    world,
):
    conn, old, new, _ = world
    conn.execute("UPDATE instrument SET isin='INE239A01016' WHERE instrument_id=%s", (old,))
    conn.execute("UPDATE instrument SET isin='INE239A01024' WHERE instrument_id=%s", (new,))
    assert store_conversion(conn, DOC, NOW) == 1
    assert store_conversion(conn, DOC, NOW) == 0  # idempotent
    row = conn.execute(
        "SELECT source_instrument_id, target_instrument_id, effective_date, ratio_num, ratio_den, absorbs_kind,"
        " verification_status, relationship_id IS NOT NULL FROM security_conversion"
    ).fetchone()
    assert row == (old, new, CHANGE, D(10), D(1), "split", "VERIFIED", True)
    (c,) = load_conversions(conn)
    assert c.absorbs == (CHANGE, "split") and c.evidence == tuple(DOC["evidence"])
    bare = {
        **DOC,
        "effective_date": "2024-02-01",
        "last_source_session": None,
        "absorbs": None,
        "verification_status": "PROVISIONAL",
    }
    assert store_conversion(conn, bare, NOW) == 1
    assert conn.execute(
        "SELECT relationship_id, absorbs_ex_date, last_source_session FROM security_conversion WHERE effective_date='2024-02-01'"
    ).fetchone() == (None, None, None)


def test_an_instruction_that_cannot_be_trusted_is_refused(world):
    conn, old, new, _ = world
    with pytest.raises(ConversionRecordError, match="no instrument with source ISIN"):
        store_conversion(conn, DOC, NOW)
    conn.execute("UPDATE instrument SET isin='INE239A01016' WHERE instrument_id=%s", (old,))
    with pytest.raises(ConversionRecordError, match="no instrument with target ISIN"):
        store_conversion(conn, DOC, NOW)
    conn.execute("UPDATE instrument SET isin='INE239A01024' WHERE instrument_id=%s", (new,))
    with pytest.raises(ConversionRecordError, match="must cite evidence"):
        store_conversion(conn, {**DOC, "evidence": []}, NOW)
    assert conn.execute("SELECT count(*) FROM security_conversion").fetchone()[0] == 0
