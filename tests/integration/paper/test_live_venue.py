# ruff: noqa: E501
"""One pipeline, two venues: a LIVE account's orders share everything with paper except where they go. The jobs that SIMULATE (fills, expiry of
unfilled approvals, the paper OMS sync, the paper reconciler and flatten) must never touch a LIVE account's real orders."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from algo.backtest.costs.policy import CostModel
from algo.core.clock import SimClock
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.paper import book, orders
from algo.paper import oms as paper_oms
from algo.risk import store as kill_switch
from tests.support.bt import put_bars
from tests.support.portal import add_user

pytestmark = pytest.mark.integration
COST = CostModel("test-flat", D(10), D(0), False)
OPEN = datetime(2026, 11, 13, 3, 45, tzinfo=UTC)  # Friday 09:15 IST
CLOSE = OPEN + timedelta(hours=6, minutes=15)
EVENING = OPEN - timedelta(hours=8)


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    iid = repo.add_instrument(x, "AAA")
    repo.add_terms(iid, date(2000, 1, 1), None, D(1), D("0.05"), D(1))
    users = []
    for name, mode in (("paper", "PAPER"), ("live", "LIVE")):
        u = add_user(conn, SimClock(EVENING), "TRADER", f"{name}@example.com")
        book.create_account(
            conn,
            u,
            strategy_id="trend_pullback",
            params={},
            initial_cash=D(100_000),
            started_on=date(2026, 11, 2),
            now=EVENING,
        )
        conn.execute("UPDATE paper_account SET mode=%s WHERE user_id=%s", (mode, u))
        users.append(u)
    conn.execute(
        "INSERT INTO live_bar_1m (instrument_id, ts, open, high, low, close, volume, ticks, partial, built_at) VALUES (%s,%s,200,200,200,200,1000,5,false,%s)",
        (iid, OPEN + timedelta(minutes=1), OPEN + timedelta(minutes=1)),
    )
    return conn, users[0], users[1], iid


def approved(conn, user, iid, qty=10):
    return conn.execute(
        "INSERT INTO paper_order (user_id, decision_day, instrument_id, side, qty, ref_price, reason, created_at, not_before, expires_at, status, decided_at, decided_by)"
        " VALUES (%s,%s,%s,'BUY',%s,200,'entry',%s,%s,%s,'APPROVED',%s,%s) RETURNING order_id",
        (user, date(2026, 11, 12), iid, qty, EVENING, OPEN, CLOSE, EVENING, user),
    ).fetchone()[0]


def status(conn, oid):
    return conn.execute("SELECT status FROM paper_order WHERE order_id=%s", (oid,)).fetchone()[0]


def test_a_live_account_can_exist_and_paper_stays_the_default(env):
    conn, paper, live, _ = env
    assert book.get_account(conn, paper)["mode"] == "PAPER"
    assert book.get_account(conn, live)["mode"] == "LIVE"
    with pytest.raises(Exception, match="paper_account_mode_check"):
        conn.execute("UPDATE paper_account SET mode='REAL' WHERE user_id=%s", (paper,))


def test_the_paper_fill_job_fills_paper_orders_and_never_a_live_one(env):
    conn, paper, live, iid = env
    p, lv = approved(conn, paper, iid), approved(conn, live, iid)
    report = orders.fill_due(conn, OPEN + timedelta(minutes=5), cost=COST, slippage_bps=D(0))
    assert status(conn, p) == "FILLED" and status(conn, lv) == "APPROVED"
    assert report.filled == 1
    booked = conn.execute("SELECT count(*) FROM paper_event WHERE user_id=%s", (live,)).fetchone()
    assert booked[0] == 0  # nothing was booked as a simulated fill


def test_an_unfilled_live_approval_is_not_failed_by_the_paper_expiry_job(env):
    conn, paper, live, iid = env
    p, lv = approved(conn, paper, iid), approved(conn, live, iid)
    orders.expire_due(conn, CLOSE + timedelta(minutes=1))
    assert status(conn, p) == "FAILED" and status(conn, lv) == "APPROVED"


def test_proposals_nobody_answered_expire_for_both_venues(env):
    conn, paper, live, iid = env
    ids = []
    for u in (paper, live):
        ids.append(
            conn.execute(
                "INSERT INTO paper_order (user_id, decision_day, instrument_id, side, qty, ref_price, reason, created_at, not_before, expires_at)"
                " VALUES (%s,%s,%s,'BUY',10,200,'entry',%s,%s,%s) RETURNING order_id",
                (u, date(2026, 11, 12), iid, EVENING, OPEN, CLOSE),
            ).fetchone()[0]
        )
    orders.expire_due(conn, CLOSE + timedelta(minutes=1))
    assert [status(conn, i) for i in ids] == ["EXPIRED", "EXPIRED"]  # the same rule for both


def test_the_paper_oms_does_not_adopt_a_live_order_into_its_log(env):
    conn, _, live, iid = env
    approved(conn, live, iid)
    oms = paper_oms.sync(conn, OPEN + timedelta(minutes=5))
    assert oms.orders == {}
    assert conn.execute("SELECT count(*) FROM oms_event").fetchone()[0] == 0


def test_the_paper_reconciler_ignores_live_accounts_and_flatten_only_queues_their_closing_order(
    env,
):
    conn, _, live, iid = env
    conn.execute(
        "INSERT INTO paper_event (user_id, day, kind, instrument_id, qty, price, commission, ref, created_at) VALUES (%s,%s,'BUY',%s,10,200,0,'x',%s)",
        (live, date(2026, 11, 3), iid, EVENING),
    )  # the live book holds 10 and has no FILLED paper order: a paper reconcile would call that a mismatch
    assert paper_oms.position_mismatches(conn) == []
    put_bars(
        conn, iid, {date(2026, 11, 12): D(200)}
    )  # flatten values the closing order at the last close
    kill_switch.change(
        conn, "flatten", None, by="o", reason="drill", now=OPEN, emergency_override=True
    )
    result = paper_oms.flatten(conn, OPEN)
    assert result.refused == []
    row = conn.execute("SELECT status FROM paper_order WHERE user_id=%s", (live,)).fetchone()
    assert (
        row[0] == "APPROVED"
    )  # made and approved by the FLATTEN, left for the live process: the paper job never sends it
    assert conn.execute("SELECT count(*) FROM oms_event").fetchone()[0] == 0
