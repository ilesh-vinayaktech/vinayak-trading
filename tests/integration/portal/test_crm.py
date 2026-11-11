from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from algo.data.store.migrate import migrate
from algo.portal import accounts, audit, crm
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


def test_notes_are_trimmed_validated_listed_newest_first_with_the_author_and_audited(db):
    ops, jane = person(db, "ops@example.com", "OPERATOR"), person(db, "jane@example.com")
    first = crm.add_note(db, actor=ops, user_id=jane, body="  Asked about Kite setup  ", now=NOW)
    crm.add_note(
        db,
        actor=ops,
        user_id=jane,
        body="Followed up by phone",
        now=datetime(2026, 11, 12, tzinfo=UTC),
    )
    notes = crm.list_notes(db, jane)
    assert (
        [n["body"] for n in notes] == ["Followed up by phone", "Asked about Kite setup"]
        and notes[0]["author"] == "Ops"
        and notes[1]["id"] == str(first)
    )
    for bad in ("", "   ", "x" * 4001):
        with pytest.raises(crm.CrmError):
            crm.add_note(db, actor=ops, user_id=jane, body=bad, now=NOW)
    for fn in (
        lambda: crm.add_note(db, actor=ops, user_id=uuid4(), body="x", now=NOW),
        lambda: crm.list_notes(db, uuid4()),
    ):
        with pytest.raises(crm.CrmError) as e:
            fn()
        assert e.value.status == 404
    assert audit.recent(db, action_prefix="crm.note_added", limit=1)[0]["target_id"] == str(jane)


def test_tags_are_normalised_unique_per_user_counted_and_removable(db):
    ops, jane, bob = (
        person(db, "ops@example.com", "OPERATOR"),
        person(db, "jane@example.com"),
        person(db, "bob@example.com"),
    )
    assert (
        crm.add_tag(db, actor=ops, user_id=jane, tag="  KYC   Pending ", now=NOW) == "kyc pending"
    )
    assert (
        crm.add_tag(db, actor=ops, user_id=jane, tag="kyc pending", now=NOW) == "kyc pending"
    )  # again: no duplicate, no second audit entry
    crm.add_tag(db, actor=ops, user_id=jane, tag="onboarding", now=NOW)
    crm.add_tag(db, actor=ops, user_id=bob, tag="onboarding", now=NOW)
    assert crm.tags_of(db, jane) == ["kyc pending", "onboarding"] and crm.tags_of(db, bob) == [
        "onboarding"
    ]
    assert crm.all_tags(db) == [
        {"tag": "kyc pending", "users": 1},
        {"tag": "onboarding", "users": 2},
    ]
    assert len(audit.recent(db, action_prefix="crm.tag_added")) == 3
    for bad in ("", "   ", "-start", "x" * 31, "bad!char"):
        with pytest.raises(crm.CrmError):
            crm.add_tag(db, actor=ops, user_id=jane, tag=bad, now=NOW)
    with pytest.raises(crm.CrmError) as e:
        crm.add_tag(db, actor=ops, user_id=uuid4(), tag="x", now=NOW)
    assert e.value.status == 404
    assert crm.remove_tag(db, actor=ops, user_id=jane, tag="Onboarding", now=NOW) is True
    assert crm.remove_tag(db, actor=ops, user_id=jane, tag="onboarding", now=NOW) is False
    assert audit.recent(db, action_prefix="crm.tag_removed", limit=1)[0]["detail"] == {
        "tag": "onboarding"
    }


def test_tasks_go_only_to_active_staff_can_be_about_a_user_filtered_and_completed(db):
    boss, ops, jane = (
        person(db, "boss@example.com", "ADMIN"),
        person(db, "ops@example.com", "OPERATOR"),
        person(db, "jane@example.com"),
    )
    held = person(db, "held@example.com", "OPERATOR", status="SUSPENDED")
    t1 = crm.create_task(
        db,
        actor=boss,
        title="  Call Jane  ",
        detail=" about Kite ",
        owner_id=ops,
        user_id=jane,
        due=date(2026, 11, 15),
        now=NOW,
    )
    t2 = crm.create_task(
        db,
        actor=boss,
        title="Review audit",
        detail="",
        owner_id=boss,
        user_id=None,
        due=None,
        now=NOW,
    )
    crm.create_task(
        db,
        actor=ops,
        title="Early one",
        detail="",
        owner_id=ops,
        user_id=None,
        due=date(2026, 11, 12),
        now=NOW,
    )
    for owner in (jane, held, uuid4()):
        with pytest.raises(crm.CrmError, match="administrator or operator"):
            crm.create_task(
                db,
                actor=boss,
                title="x",
                detail="",
                owner_id=owner,
                user_id=None,
                due=None,
                now=NOW,
            )
    for title, detail in (("", ""), ("x" * 201, ""), ("ok", "x" * 4001)):
        with pytest.raises(crm.CrmError):
            crm.create_task(
                db,
                actor=boss,
                title=title,
                detail=detail,
                owner_id=boss,
                user_id=None,
                due=None,
                now=NOW,
            )
    with pytest.raises(crm.CrmError) as e:
        crm.create_task(
            db, actor=boss, title="x", detail="", owner_id=boss, user_id=uuid4(), due=None, now=NOW
        )
    assert e.value.status == 404
    assert [t["title"] for t in crm.list_tasks(db)] == [
        "Early one",
        "Call Jane",
        "Review audit",
    ]  # by due date, undated last
    mine = crm.list_tasks(db, owner_id=ops)
    assert {t["title"] for t in mine} == {"Call Jane", "Early one"} and next(
        t for t in mine if t["title"] == "Call Jane"
    )["about"] == "Jane"
    assert [t["title"] for t in crm.list_tasks(db, user_id=jane)] == ["Call Jane"]
    crm.set_task_status(db, actor=ops, task_id=t1, status="DONE", now=NOW)
    assert [t["title"] for t in crm.list_tasks(db, status="OPEN")] == ["Early one", "Review audit"]
    done = crm.list_tasks(db, status="DONE")[0]
    assert done["completed_at"] == NOW and done["detail"] == "about Kite"
    assert crm.list_tasks(db)[-1]["status"] == "DONE"  # finished work sinks to the bottom
    crm.set_task_status(db, actor=ops, task_id=t1, status="OPEN", now=NOW)
    assert crm.list_tasks(db, status="DONE") == []
    assert len(crm.list_tasks(db, limit=0)) == 1
    for fn in (
        lambda: crm.list_tasks(db, status="WAT"),
        lambda: crm.set_task_status(db, actor=ops, task_id=t2, status="WAT", now=NOW),
    ):
        with pytest.raises(crm.CrmError):
            fn()
    with pytest.raises(crm.CrmError) as e2:
        crm.set_task_status(db, actor=ops, task_id=uuid4(), status="DONE", now=NOW)
    assert e2.value.status == 404
    assert {e["action"] for e in audit.recent(db, action_prefix="crm.task")} == {
        "crm.task_created",
        "crm.task_done",
        "crm.task_reopened",
    }
