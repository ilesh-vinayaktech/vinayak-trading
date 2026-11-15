from datetime import date, timedelta

import psycopg
import pytest

from algo.data.universe import (
    Interval,
    UniverseError,
    UniverseGap,
    UniverseInconsistent,
    add_event,
    constituents_on,
    coverage_report,
    covered,
    declare_coverage,
    intervals,
    members_on,
    set_event_status,
    verify_coverage,
)  # fmt: skip
from tests.support.bt import NOW, make_env

pytestmark = pytest.mark.integration
IDX = "NIFTY200"
START, JUN15, JUN20, JUN30, JUL5 = (date(2020, 1, 1), date(2021, 6, 15), date(2021, 6, 20),
                                    date(2021, 6, 30), date(2021, 7, 5))  # fmt: skip


@pytest.fixture
def env(conn):
    return make_env(conn)


def ev(conn, iid, kind, eff, ann=None, **kw):
    return add_event(conn, index_id=IDX, instrument_id=iid, symbol="S", event_type=kind,
                     announcement_date=ann or eff, effective_from=eff, source_url="https://nse/c1",
                     source_hash="abc", now=NOW, **kw)  # fmt: skip


def verified(conn, *ids):
    for i in ids:
        set_event_status(conn, i, "VERIFIED", by="owner", now=NOW)


def cover(conn, strict_verified=True, until=None):
    c = declare_coverage(conn, IDX, START, until, "initial snapshot + all circulars", NOW)
    if strict_verified:
        verify_coverage(conn, c, by="owner", now=NOW)
    return c


def test_membership_is_derived_from_events_not_from_a_snapshot(env):
    conn, a, b = env
    cover(conn)
    verified(conn, ev(conn, a, "ADD", START), ev(conn, b, "ADD", START),
             ev(conn, b, "REMOVE", JUN30, JUN15), ev(conn, b, "ADD", date(2022, 1, 3)))  # fmt: skip
    assert members_on(conn, IDX, date(2021, 1, 4)) == {a, b}
    assert members_on(conn, IDX, date(2021, 6, 29)) == {a, b}
    assert members_on(conn, IDX, JUN30) == {a}  # removal is effective on the stated day
    assert members_on(conn, IDX, date(2022, 1, 3)) == {a, b}  # re-entry
    assert intervals(conn, IDX) == [Interval(a, START, None), Interval(b, START, JUN30),
                                    Interval(b, date(2022, 1, 3), None)]  # fmt: skip


def test_a_future_announcement_cannot_leak_into_an_earlier_decision(env):
    conn, a, b = env
    cover(conn)
    verified(conn, ev(conn, a, "ADD", START), ev(conn, b, "ADD", JUN30, ann=JUN15))
    assert members_on(conn, IDX, JUN20) == {a}  # not yet effective
    assert members_on(conn, IDX, JUN30, known_on=JUN20) == {
        a,
        b,
    }  # announced 15th: legitimately known
    assert members_on(conn, IDX, JUN30, known_on=date(2021, 6, 10)) == {a}  # not yet announced
    assert members_on(conn, IDX, JUN30) == {a, b}


def test_days_outside_verified_coverage_are_unknown_not_todays_list(env):
    conn, a, _ = env
    verified(conn, ev(conn, a, "ADD", START))
    with pytest.raises(UniverseGap, match="not covered by verified history"):
        members_on(conn, IDX, JUN20)  # no coverage declared at all
    cover(conn, strict_verified=False, until=date(2021, 12, 31))
    with pytest.raises(UniverseGap, match="verified"):
        members_on(conn, IDX, JUN20)  # declared but unverified
    assert members_on(conn, IDX, JUN20, strict=False) == {a}  # research mode accepts it
    with pytest.raises(UniverseGap, match="declared"):
        members_on(conn, IDX, date(2022, 6, 1), strict=False)  # beyond the declared end
    with pytest.raises(UniverseGap):
        members_on(conn, IDX, date(2019, 12, 31), strict=False)  # before it starts


def test_provisional_events_count_only_in_research_mode_and_rejected_never(env):
    conn, a, b = env
    cover(conn)
    verified(conn, ev(conn, a, "ADD", START))
    ev(conn, b, "ADD", START)  # provisional
    rejected = ev(conn, b, "ADD", date(2020, 6, 1))
    set_event_status(conn, rejected, "REJECTED", by="owner", now=NOW)
    assert members_on(conn, IDX, JUN20) == {a}
    assert members_on(conn, IDX, JUN20, strict=False) == {a, b}
    assert intervals(conn, IDX, strict=False) == [
        Interval(a, START, None),
        Interval(b, START, None),
    ]


def test_an_add_while_already_a_member_is_reported_not_guessed_away(env):
    conn, a, _ = env
    cover(conn)
    verified(conn, ev(conn, a, "ADD", START), ev(conn, a, "ADD", JUN30))
    with pytest.raises(UniverseInconsistent, match="ADDed on 2021-06-30 while already a member"):
        members_on(conn, IDX, JUL5)
    assert "ADDed on" in coverage_report(conn, IDX)["inconsistency"]
    assert not coverage_report(conn, IDX)["strict_ready"]


def test_a_remove_without_a_membership_is_reported(env):
    conn, _, b = env
    verified(conn, ev(conn, b, "REMOVE", JUN30))
    with pytest.raises(UniverseInconsistent, match="but not a member"):
        intervals(conn, IDX)


def test_events_are_validated_and_append_only(env):
    conn, a, _ = env
    with pytest.raises(UniverseError, match="ADD or REMOVE"):
        ev(conn, a, "BUY", START)
    with pytest.raises(UniverseError, match="instrument or a constituent key"):
        add_event(conn, index_id=IDX, instrument_id=None, symbol="S", event_type="ADD",
                  announcement_date=START, effective_from=START, source_url="u", source_hash="x", now=NOW)  # fmt: skip
    with pytest.raises(UniverseError, match="source url and document hash"):
        add_event(conn, index_id=IDX, instrument_id=a, symbol="S", event_type="ADD",
                  announcement_date=START, effective_from=START, source_url="", source_hash="x", now=NOW)  # fmt: skip
    e = ev(conn, a, "ADD", START)
    with pytest.raises(psycopg.errors.UniqueViolation):
        ev(conn, a, "ADD", START)
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        conn.execute("UPDATE index_membership_event SET effective_from = effective_from + 1")
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        conn.execute("DELETE FROM index_membership_event")
    set_event_status(conn, e, "VERIFIED", by="owner", now=NOW)  # verification may change
    with pytest.raises(UniverseError, match="status must be one of"):
        set_event_status(conn, e, "MAYBE", by="owner", now=NOW)
    with pytest.raises(UniverseError, match="reviewer name"):
        set_event_status(conn, e, "VERIFIED", by="", now=NOW)
    with pytest.raises(UniverseError, match="no event 999"):
        set_event_status(conn, 999, "VERIFIED", by="owner", now=NOW)


def test_coverage_needs_a_basis_a_reviewer_and_a_real_row(env):
    conn, _, _ = env
    with pytest.raises(UniverseError, match="say how completeness"):
        declare_coverage(conn, IDX, START, None, " ", NOW)
    with pytest.raises(UniverseError, match="reviewer name"):
        verify_coverage(conn, 1, by="", now=NOW)
    with pytest.raises(UniverseError, match="no coverage 999"):
        verify_coverage(conn, 999, by="owner", now=NOW)
    c = cover(conn, until=date(2021, 12, 31))
    assert covered(conn, IDX, JUN20) and not covered(conn, IDX, date(2022, 1, 1)) and c > 0


def test_the_coverage_report_states_what_is_established(env):
    conn, a, b = env
    r = coverage_report(conn, IDX)
    assert (
        r["coverage"] == []
        and not r["strict_ready"]
        and r["events"] == {"VERIFIED": 0, "PROVISIONAL": 0, "REJECTED": 0}
    )
    cover(conn, until=date(2021, 12, 31))
    verified(conn, ev(conn, a, "ADD", START))
    pending = ev(conn, b, "ADD", START)
    r = coverage_report(conn, IDX)
    assert r["events"] == {"VERIFIED": 1, "PROVISIONAL": 1, "REJECTED": 0} and not r["strict_ready"]
    assert r["coverage"][0] == {"from": "2020-01-01", "until": "2021-12-31", "status": "VERIFIED",
                                "basis": "initial snapshot + all circulars"}  # fmt: skip
    verified(conn, pending)
    assert coverage_report(conn, IDX)["strict_ready"]


def test_the_actual_and_the_known_date_are_kept_apart(env):
    conn, a, _ = env
    ev(conn, a, "ADD", JUN15, ann=JUN30)  # really effective 15 June, only announced 30 June
    cover(conn, strict_verified=False)
    verified_ids = [r[0] for r in conn.execute("SELECT event_id FROM index_membership_event")]
    verified(conn, *verified_ids)
    assert conn.execute(
        "SELECT effective_from, announcement_date FROM index_membership_event"
    ).fetchone() == (JUN15, JUN30)
    assert (
        members_on(conn, IDX, JUN20, strict=False) == set()
    )  # a decision on 20 June could not have known
    assert members_on(conn, IDX, JUN20, known_on=JUL5, strict=False) == {a}  # a later reader knows
    assert members_on(conn, IDX, JUN20, historical=True, strict=False) == {
        a
    }  # the historical record: who WAS a member


def test_a_constituent_without_an_instrument_is_a_member_but_not_a_tradable_one(env):
    conn, a, _ = env
    for key, kind, eff in (("p:DUMMYX", "ADD", START), ("p:DUMMYX", "REMOVE", JUN15)):
        add_event(conn, index_id=IDX, instrument_id=None, constituent_key=key, symbol="DUMMYX", event_type=kind,
                  announcement_date=eff, effective_from=eff, source_url="u", source_hash="x", now=NOW)  # fmt: skip
    ev(conn, a, "ADD", JUN15)
    cover(conn, strict_verified=False)
    assert constituents_on(conn, IDX, JUN15 - timedelta(days=1), strict=False) == {"p:DUMMYX"}
    assert constituents_on(conn, IDX, JUN15, strict=False) == {
        f"i:{a}"
    }  # the real listing replaces the placeholder
    assert (
        members_on(conn, IDX, JUN15 - timedelta(days=1), strict=False) == set()
    )  # not tradable: never in the instrument universe
    assert [i.instrument_id for i in intervals(conn, IDX, strict=False)] == [a]
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO index_membership_event (index_id,constituent_key,symbol_at_event,event_type,announcement_date,"
                     "effective_from,source_url,source_hash,ingested_at) VALUES ('X','DUMMY','D','ADD',now(),now(),'u','h',now())")  # fmt: skip


def test_constituents_outside_coverage_are_unknown_too(env):
    conn, _, _ = env
    with pytest.raises(UniverseGap, match="not covered by verified history"):
        constituents_on(conn, IDX, JUN20)
