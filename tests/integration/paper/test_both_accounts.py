# ruff: noqa: E501
"""A person can run a paper account and a live account side by side: separate keys, separate books, one of each mode, and an approval records the PERSON
(paper_order.decided_by points at the portal user, not at the account key)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from algo.core.clock import SimClock
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.paper import book, orders
from tests.support.portal import add_user

pytestmark = pytest.mark.integration
OPEN = datetime(2026, 11, 13, 3, 45, tzinfo=UTC)
CLOSE = OPEN + timedelta(hours=6, minutes=15)
EVENING = OPEN - timedelta(hours=8)
D0 = date(2026, 11, 2)


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    iid = repo.add_instrument(x, "AAA")
    repo.add_terms(iid, date(2000, 1, 1), None, D(1), D("0.05"), D(1))
    owner = add_user(conn, SimClock(EVENING), "TRADER", "both@example.com")
    return conn, owner, iid


def open_account(conn, owner, mode, cash="100000"):
    book.create_account(
        conn,
        owner,
        strategy_id="trend_pullback",
        params={},
        initial_cash=D(cash),
        started_on=D0,
        now=EVENING,
        mode=mode,
    )
    return book.account_key(owner, mode)


def proposal(conn, key, iid):
    return conn.execute(
        "INSERT INTO paper_order (user_id, decision_day, instrument_id, side, qty, ref_price, reason, created_at, not_before, expires_at)"
        " VALUES (%s,%s,%s,'BUY',10,200,'entry',%s,%s,%s) RETURNING order_id",
        (key, date(2026, 11, 12), iid, EVENING, OPEN, CLOSE),
    ).fetchone()[0]


def test_the_paper_key_is_the_person_and_the_live_key_is_its_own_and_stable(env):
    _, owner, _ = env
    assert book.account_key(owner, "PAPER") == owner
    assert book.account_key(owner, "LIVE") != owner
    assert book.account_key(owner, "LIVE") == book.account_key(owner, "LIVE")
    with pytest.raises(book.PaperError, match="mode"):
        book.account_key(owner, "REAL")


def test_one_person_can_have_one_account_of_each_mode_and_no_more(env):
    conn, owner, _ = env
    paper, live = open_account(conn, owner, "PAPER"), open_account(conn, owner, "LIVE", "50000")
    assert book.get_account(conn, paper)["mode"] == "PAPER"
    assert book.get_account(conn, live)["mode"] == "LIVE"
    assert book.get_account(conn, live)["owner_user_id"] == owner
    with pytest.raises(book.PaperError, match="already has"):
        open_account(conn, owner, "LIVE")


def test_the_two_books_are_independent(env):
    conn, owner, iid = env
    paper, live = open_account(conn, owner, "PAPER"), open_account(conn, owner, "LIVE", "50000")
    book.record_fill(
        conn, live, day=D0, side="BUY", iid=iid, qty=D(10), price=D(100),
        commission=D(0), charges=[], ref="r", now=EVENING,
    )  # fmt: skip
    assert book.load(conn, paper).cash == D(100000) and book.load(conn, paper).qty(iid) == 0
    assert book.load(conn, live).cash == D(49000) and book.load(conn, live).qty(iid) == 10


def test_an_approval_on_the_live_account_records_the_person_who_answered(env):
    conn, owner, iid = env
    live = open_account(conn, owner, "LIVE")
    oid = proposal(conn, live, iid)
    orders.approve(conn, oid, user_id=live, now=OPEN)
    row = conn.execute(
        "SELECT status, decided_by FROM paper_order WHERE order_id=%s", (oid,)
    ).fetchone()
    assert row == ("APPROVED", owner)


def test_a_paper_approval_still_records_the_person(env):
    conn, owner, iid = env
    paper = open_account(conn, owner, "PAPER")
    oid = proposal(conn, paper, iid)
    orders.approve(conn, oid, user_id=paper, now=OPEN)
    row = conn.execute("SELECT decided_by FROM paper_order WHERE order_id=%s", (oid,)).fetchone()
    assert row[0] == owner
