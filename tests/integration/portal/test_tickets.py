from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from algo.data.store.migrate import migrate
from algo.portal import accounts, audit, tickets
from tests.support.portal import FAST

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)


@pytest.fixture
def db(conn):
    migrate(conn)
    return conn


def person(db, email, role="TRADER", status="ACTIVE"):
    return accounts.create_user(
        db,
        FAST,
        email=email,
        display_name=email.split("@")[0].title(),
        role=role,
        password="violet-harbor-lantern-42",
        now=NOW,
        status=status,
    )


def open_ticket(
    db, uid, subject="Cannot connect Kite", body="It says invalid token", priority="NORMAL", now=NOW
):
    number = tickets.create(db, actor=uid, subject=subject, body=body, priority=priority, now=now)
    return db.execute("SELECT ticket_id FROM portal_ticket WHERE number=%s", (number,)).fetchone()[
        0
    ], number


def test_a_ticket_starts_open_with_its_first_message_and_gets_a_running_number(db):
    jane = person(db, "jane@example.com")
    t1, n1 = open_ticket(db, jane, priority="HIGH")
    _, n2 = open_ticket(db, jane, subject="Second")
    assert n2 == n1 + 1
    t = tickets.get(db, actor=jane, role="TRADER", ticket_id=t1)
    assert (t["status"], t["priority"], t["requester"], t["assignee"]) == (
        "OPEN",
        "HIGH",
        "Jane",
        None,
    )
    assert [(m["body"], m["internal"], m["mine"]) for m in t["messages"]] == [
        ("It says invalid token", False, True)
    ]
    for kw in (
        dict(subject=" ", body="x"),
        dict(subject="x" * 201, body="x"),
        dict(subject="s", body=""),
        dict(subject="s", body="x" * 8001),
        dict(subject="s", body="b", priority="URGENT"),
    ):
        with pytest.raises(tickets.TicketError):
            tickets.create(db, actor=jane, **({"priority": "NORMAL"} | kw), now=NOW)
    assert (
        audit.recent(db, action_prefix="ticket.created", limit=1)[0]["detail"]["priority"]
        == "NORMAL"
    )


def test_people_see_only_their_own_tickets_and_a_foreign_id_looks_like_a_missing_one(db):
    jane, bob = person(db, "jane@example.com"), person(db, "bob@example.com")
    ops = person(db, "ops@example.com", "OPERATOR")
    tj, _ = open_ticket(db, jane)
    open_ticket(db, bob, subject="Bob's")
    assert [t["subject"] for t in tickets.list_tickets(db, actor=jane, role="TRADER")["items"]] == [
        "Cannot connect Kite"
    ]
    assert tickets.list_tickets(db, actor=ops, role="OPERATOR")["total"] == 2
    assert tickets.list_tickets(db, actor=ops, role="OPERATOR", mine_only=True)["total"] == 0
    for fn in (
        lambda: tickets.get(db, actor=bob, role="TRADER", ticket_id=tj),
        lambda: tickets.get(db, actor=bob, role="TRADER", ticket_id=uuid4()),
        lambda: tickets.reply(
            db, actor=bob, role="TRADER", ticket_id=tj, body="hi", internal=False, now=NOW
        ),
        lambda: tickets.set_status(
            db, actor=bob, role="TRADER", ticket_id=tj, status="CLOSED", now=NOW
        ),
        lambda: tickets.assign(
            db, actor=bob, role="TRADER", ticket_id=tj, assignee_id=ops, now=NOW
        ),
    ):
        with pytest.raises(tickets.TicketError) as e:
            fn()
        assert e.value.status == 404


def test_the_queue_filters_by_status_and_assignee_and_pages(db):
    jane, ops, boss = (
        person(db, "jane@example.com"),
        person(db, "ops@example.com", "OPERATOR"),
        person(db, "boss@example.com", "ADMIN"),
    )
    a, _ = open_ticket(db, jane, subject="A", now=NOW)
    b, _ = open_ticket(db, jane, subject="B", now=NOW + timedelta(minutes=1))
    tickets.assign(
        db, actor=boss, role="ADMIN", ticket_id=a, assignee_id=ops, now=NOW + timedelta(minutes=2)
    )
    tickets.set_status(
        db,
        actor=ops,
        role="OPERATOR",
        ticket_id=b,
        status="RESOLVED",
        now=NOW + timedelta(minutes=3),
    )

    def q(**kw):
        return [
            t["subject"]
            for t in tickets.list_tickets(db, actor=ops, role="OPERATOR", **kw)["items"]
        ]

    assert q() == ["B", "A"]  # most recently touched first
    assert q(status="OPEN") == ["A"] and q(assignee_id=ops) == ["A"]
    assert q(limit=1, offset=1) == ["A"]
    assert [
        t["subject"]
        for t in tickets.list_tickets(db, actor=jane, role="TRADER", assignee_id=ops)["items"]
    ] == ["B", "A"]  # a requester cannot filter by staff
    with pytest.raises(tickets.TicketError):
        q(status="WAT")


def test_the_conversation_moves_the_status_and_internal_notes_stay_hidden_from_the_requester(db):
    jane, ops = person(db, "jane@example.com"), person(db, "ops@example.com", "OPERATOR")
    t, _ = open_ticket(db, jane)
    tickets.reply(
        db,
        actor=ops,
        role="OPERATOR",
        ticket_id=t,
        body="Which browser?",
        internal=False,
        now=NOW + timedelta(minutes=1),
    )
    head = tickets.get(db, actor=ops, role="OPERATOR", ticket_id=t)
    assert (head["status"], head["assignee"]) == (
        "PENDING",
        "Ops",
    )  # staff answered: waiting on the requester, and the answerer owns it
    tickets.reply(
        db,
        actor=ops,
        role="OPERATOR",
        ticket_id=t,
        body="Looks like a token expiry, check with Zerodha",
        internal=True,
        now=NOW + timedelta(minutes=2),
    )
    assert (
        tickets.get(db, actor=ops, role="OPERATOR", ticket_id=t)["status"] == "PENDING"
    )  # an internal note changes nothing
    seen = tickets.get(db, actor=jane, role="TRADER", ticket_id=t)
    assert [m["body"] for m in seen["messages"]] == [
        "It says invalid token",
        "Which browser?",
    ]  # no internal note
    assert [m["mine"] for m in seen["messages"]] == [True, False]
    assert len(tickets.get(db, actor=ops, role="OPERATOR", ticket_id=t)["messages"]) == 3
    tickets.reply(
        db,
        actor=jane,
        role="TRADER",
        ticket_id=t,
        body="Firefox",
        internal=False,
        now=NOW + timedelta(minutes=3),
    )
    assert (
        tickets.get(db, actor=jane, role="TRADER", ticket_id=t)["status"] == "OPEN"
    )  # she answered: staff again
    # replies that change nothing: the requester adding to an open ticket, staff adding while already waiting on the requester
    tickets.reply(
        db,
        actor=jane,
        role="TRADER",
        ticket_id=t,
        body="More detail",
        internal=False,
        now=NOW + timedelta(minutes=4),
    )
    assert tickets.get(db, actor=jane, role="TRADER", ticket_id=t)["status"] == "OPEN"
    tickets.set_status(
        db,
        actor=ops,
        role="OPERATOR",
        ticket_id=t,
        status="PENDING",
        now=NOW + timedelta(minutes=5),
    )
    tickets.reply(
        db,
        actor=ops,
        role="OPERATOR",
        ticket_id=t,
        body="Noted",
        internal=False,
        now=NOW + timedelta(minutes=6),
    )
    assert tickets.get(db, actor=jane, role="TRADER", ticket_id=t)["status"] == "PENDING"
    with pytest.raises(tickets.TicketError, match="only staff") as e:
        tickets.reply(db, actor=jane, role="TRADER", ticket_id=t, body="x", internal=True, now=NOW)
    assert e.value.status == 403
    for body in ("", "   ", "x" * 8001):
        with pytest.raises(tickets.TicketError):
            tickets.reply(
                db, actor=jane, role="TRADER", ticket_id=t, body=body, internal=False, now=NOW
            )
    assert {e["action"] for e in audit.recent(db, action_prefix="ticket.reply")} == {
        "ticket.reply",
        "ticket.reply_internal",
    }


def test_a_resolved_ticket_reopens_when_the_requester_returns_and_a_closed_one_stays_closed(db):
    jane, ops = person(db, "jane@example.com"), person(db, "ops@example.com", "OPERATOR")
    t, _ = open_ticket(db, jane)
    tickets.set_status(db, actor=ops, role="OPERATOR", ticket_id=t, status="RESOLVED", now=NOW)
    tickets.reply(
        db, actor=jane, role="TRADER", ticket_id=t, body="Still broken", internal=False, now=NOW
    )
    assert tickets.get(db, actor=jane, role="TRADER", ticket_id=t)["status"] == "OPEN"
    tickets.set_status(
        db, actor=jane, role="TRADER", ticket_id=t, status="CLOSED", now=NOW
    )  # a requester may close their own
    for who, role in ((jane, "TRADER"), (ops, "OPERATOR")):
        with pytest.raises(tickets.TicketError, match="closed") as e:
            tickets.reply(
                db, actor=who, role=role, ticket_id=t, body="more", internal=False, now=NOW
            )
        assert e.value.status == 409


def test_status_changes_are_staff_only_except_closing_your_own_and_are_audited_once(db):
    jane, ops = person(db, "jane@example.com"), person(db, "ops@example.com", "OPERATOR")
    t, _ = open_ticket(db, jane)
    with pytest.raises(tickets.TicketError, match="close your own") as e:
        tickets.set_status(db, actor=jane, role="TRADER", ticket_id=t, status="RESOLVED", now=NOW)
    assert e.value.status == 403
    with pytest.raises(tickets.TicketError):
        tickets.set_status(db, actor=ops, role="OPERATOR", ticket_id=t, status="WAT", now=NOW)
    tickets.set_status(db, actor=ops, role="OPERATOR", ticket_id=t, status="PENDING", now=NOW)
    tickets.set_status(
        db, actor=ops, role="OPERATOR", ticket_id=t, status="PENDING", now=NOW
    )  # unchanged: nothing recorded again
    changes = audit.recent(db, action_prefix="ticket.status_changed")
    assert len(changes) == 1 and changes[0]["detail"] == {"from": "OPEN", "to": "PENDING"}


def test_assignment_goes_only_to_active_staff_and_can_be_cleared(db):
    jane, ops, boss = (
        person(db, "jane@example.com"),
        person(db, "ops@example.com", "OPERATOR"),
        person(db, "boss@example.com", "ADMIN"),
    )
    held = person(db, "held@example.com", "OPERATOR", status="SUSPENDED")
    t, _ = open_ticket(db, jane)
    for who in (jane, held, uuid4()):
        with pytest.raises(tickets.TicketError, match="administrator or operator"):
            tickets.assign(db, actor=boss, role="ADMIN", ticket_id=t, assignee_id=who, now=NOW)
    tickets.assign(db, actor=boss, role="ADMIN", ticket_id=t, assignee_id=ops, now=NOW)
    assert tickets.get(db, actor=boss, role="ADMIN", ticket_id=t)["assignee"] == "Ops"
    tickets.assign(db, actor=boss, role="ADMIN", ticket_id=t, assignee_id=None, now=NOW)
    assert tickets.get(db, actor=boss, role="ADMIN", ticket_id=t)["assignee_id"] is None
    assert len(audit.recent(db, action_prefix="ticket.assigned")) == 2
