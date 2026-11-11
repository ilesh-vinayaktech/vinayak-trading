from datetime import UTC, date, datetime
from decimal import Decimal as D

import psycopg
import pytest

from algo.core.clock import SimClock
from algo.data.adjust.factors import ActionRecord
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.paper import book
from tests.support.portal import add_user

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 12, 4, 0, tzinfo=UTC)
D0 = date(2026, 11, 2)


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    a, b = repo.add_instrument(x, "AAA"), repo.add_instrument(x, "BBB")
    clock = SimClock(NOW)
    jane = add_user(conn, clock, "TRADER", "jane@example.com")
    bob = add_user(conn, clock, "TRADER", "bob@example.com")
    return conn, jane, bob, a, b


def open_account(conn, user, cash="100000"):
    return book.create_account(
        conn,
        user,
        strategy_id="trend_pullback",
        params={"max_positions": 10},
        initial_cash=D(cash),
        started_on=D0,
        now=NOW,
    )


def action(ex, kind, num=None, den=None, amount=None, status="ok"):
    return ActionRecord(ex, kind, status, num, den, amount, NOW)


def fill(conn, user, iid, side="BUY", qty=10, price=100, ref="r", commission=0, charges=()):
    return book.record_fill(
        conn,
        user,
        day=D0,
        side=side,
        iid=iid,
        qty=D(qty),
        price=D(price),
        commission=D(commission),
        charges=list(charges),
        ref=ref,
        now=NOW,
    )


def test_each_user_gets_their_own_account_once_with_the_money_they_start_with(env):
    conn, jane, bob, *_ = env
    open_account(conn, jane)
    open_account(conn, bob, "50000")
    assert book.load(conn, jane).cash == D(100000) and book.load(conn, bob).cash == D(50000)
    acct = book.get_account(conn, jane)
    assert (acct["strategy_id"], acct["mode"], acct["enabled"], acct["attention"]) == (
        "trend_pullback",
        "PAPER",
        True,
        None,
    )
    assert acct["params"] == {"max_positions": 10} and acct["initial_cash"] == D(100000)
    assert book.get_account(conn, add_user(conn, SimClock(NOW), "VIEWER", "v@example.com")) is None
    with pytest.raises(book.PaperError, match="already has"):
        open_account(conn, jane)
    with pytest.raises(book.PaperError, match="starting cash"):
        open_account(conn, add_user(conn, SimClock(NOW), "TRADER", "t@example.com"), "0")


def test_real_trading_is_not_available_the_mode_cannot_be_anything_but_paper(env):
    conn, jane, *_ = env
    open_account(conn, jane)
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE paper_account SET mode='REAL' WHERE user_id=%s", (jane,))


def test_fills_move_cash_and_shares_and_the_books_reconcile(env):
    conn, jane, bob, a, _ = env
    open_account(conn, jane)
    open_account(conn, bob)
    assert fill(conn, jane, a, "BUY", 100, 200, "o1", 10, [("STT", D("2.5"))])
    assert fill(conn, jane, a, "SELL", 40, 210, "o2", 5)
    ledger = book.load(conn, jane)
    assert ledger.qty(a) == D(60) and ledger.quantities() == {a: D(60)}
    assert ledger.cash == D(100000) - 20000 - 10 - D("2.5") + 8400 - 5
    assert ledger.reconcile({a: D(205)}) == []
    assert book.load(conn, bob).quantities() == {}  # someone else's account is untouched


def test_a_fill_that_cannot_happen_is_refused_and_leaves_nothing_behind(env):
    conn, jane, _, a, _ = env
    open_account(conn, jane, "1000")
    with pytest.raises(book.PaperError, match="not enough cash"):
        fill(conn, jane, a, "BUY", 100, 200, "big")
    with pytest.raises(book.PaperError, match="do not hold"):
        fill(conn, jane, a, "SELL", 1, 200, "short")
    with pytest.raises(book.PaperError, match="side"):
        fill(conn, jane, a, "HOLD", 1, 1, "x")
    assert conn.execute("SELECT count(*) FROM paper_event").fetchone() == (0,)


def test_posting_the_same_reference_twice_changes_nothing(env):
    conn, jane, _, a, _ = env
    open_account(conn, jane)
    assert fill(conn, jane, a, ref="once") is True
    assert fill(conn, jane, a, ref="once") is False
    assert book.load(conn, jane).qty(a) == D(10)


def test_the_event_log_is_append_only(env):
    conn, jane, _, a, _ = env
    open_account(conn, jane)
    fill(conn, jane, a, qty=1)
    for sql in ("UPDATE paper_event SET qty=99", "DELETE FROM paper_event", "TRUNCATE paper_event"):
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute(sql)


def test_splits_and_dividends_reach_held_shares_once_and_only_in_the_window(env):
    conn, jane, _, a, b = env
    open_account(conn, jane)
    fill(conn, jane, a, qty=100, price=200)
    acts = {
        a: [
            action(date(2026, 10, 1), "split", D(2), D(1)),  # before the account existed: ignored
            action(date(2026, 11, 5), "split", D(2), D(1)),
            action(date(2026, 11, 6), "dividend", amount=D(3)),
            action(date(2026, 11, 20), "dividend", amount=D(9)),  # after the date we catch up to
        ],
        b: [action(date(2026, 11, 5), "split", D(5), D(1))],  # never held
    }
    assert book.apply_actions(conn, jane, acts, through=date(2026, 11, 10), now=NOW) == 2
    ledger = book.load(conn, jane)
    assert ledger.qty(a) == D(200) and ledger.cost_basis(a) == D(20000)
    assert ledger.cash == D(100000) - 20000 + 200 * 3
    assert book.get_account(conn, jane)["actions_through"] == date(2026, 11, 10)
    assert book.apply_actions(conn, jane, acts, through=date(2026, 11, 10), now=NOW) == 0
    # a crash that lost the window pointer must not double-apply anything either
    conn.execute("UPDATE paper_account SET actions_through=%s WHERE user_id=%s", (D0, jane))
    assert book.apply_actions(conn, jane, acts, through=date(2026, 11, 10), now=NOW) == 0
    assert book.load(conn, jane).qty(a) == D(200)


def test_an_action_the_books_cannot_value_pauses_the_account_instead_of_guessing(env):
    conn, jane, _, a, _ = env
    open_account(conn, jane)
    fill(conn, jane, a)
    acts = {
        a: [
            action(date(2026, 11, 5), "rights"),
            action(date(2026, 11, 6), "split", status="review"),
        ]
    }
    assert book.apply_actions(conn, jane, acts, through=date(2026, 11, 10), now=NOW) == 2
    note = book.get_account(conn, jane)["attention"]
    assert "rights" in note and "split" in note
    assert len(book.load(conn, jane).unmodelled()) == 2
    book.clear_attention(conn, jane)
    assert book.get_account(conn, jane)["attention"] is None


def test_an_account_can_be_switched_off_and_on(env):
    conn, jane, *_ = env
    open_account(conn, jane)
    book.set_enabled(conn, jane, False)
    assert book.get_account(conn, jane)["enabled"] is False
    book.set_enabled(conn, jane, True)
    assert book.get_account(conn, jane)["enabled"] is True
    with pytest.raises(book.PaperError, match="no paper account"):
        book.set_enabled(conn, add_user(conn, SimClock(NOW), "VIEWER", "v@example.com"), False)
