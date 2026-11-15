# ruff: noqa: E501
from datetime import date

import pytest

from algo.data.membership_audit import audit
from algo.data.universe import add_event, declare_coverage, set_event_status, verify_coverage
from tests.support.bt import NOW, make_env, put_bars

pytestmark = pytest.mark.integration
IDX = "NIFTY200"
S1, S2, S3, S4 = (date(2021, 6, d) for d in (1, 2, 3, 4))
SESSIONS = [S1, S2, S3, S4]


def ev(conn, key, kind, eff, ann=None, iid=None, verified=True):
    e = add_event(conn, index_id=IDX, instrument_id=iid, constituent_key=key, symbol=key[2:], event_type=kind,
                  announcement_date=ann or eff, effective_from=eff, source_url="u", source_hash="h", now=NOW)  # fmt: skip
    if verified:
        set_event_status(conn, e, "VERIFIED", by="owner", now=NOW)


@pytest.fixture
def world(conn):
    _, a, b = make_env(conn)
    ev(conn, f"i:{a}", "ADD", S1, iid=a)
    ev(conn, f"i:{b}", "ADD", S2, ann=S3, iid=b)  # really a member from S2, knowable only from S3
    ev(conn, "p:DUMMYX", "ADD", S1)
    ev(conn, "p:DUMMYX", "REMOVE", S3)
    ev(conn, "s:ZZZ", "ADD", S1)
    put_bars(conn, a, {d: 10 for d in SESSIONS})
    put_bars(conn, b, {S2: 10, S4: 10})  # no bar on S3
    c = declare_coverage(conn, IDX, S1, S4, "test", NOW)
    verify_coverage(conn, c, by="owner", now=NOW)
    return conn, a, b


def test_it_reports_what_is_not_knowable_not_tradable_or_not_priced(world):
    conn, a, b = world
    r = audit(conn, IDX, SESSIONS)
    assert r.sessions == 4 and r.unverified == 0
    assert r.retrospective == 1  # S2: b was a member, but that was announced on S3
    assert r.by_design == {
        "p:DUMMYX": (S1, S2, 2)
    }  # a zero-price placeholder: a member, not investable, by NSE design
    assert r.untradable == {
        "s:ZZZ": (S1, S4, 4)
    }  # a member with no instrument that is not a placeholder
    assert r.missing_bars == {b: (S3, S3, 1)}
    assert a not in r.missing_bars


def test_sessions_outside_verified_coverage_are_counted_not_guessed(world):
    conn, _, _ = world
    r = audit(conn, IDX, [*SESSIONS, date(2021, 6, 7)])  # coverage ends S4
    assert r.sessions == 5 and r.unverified == 1


def test_no_sessions_is_an_empty_audit(world):
    conn, _, _ = world
    r = audit(conn, IDX, [])
    assert (
        r.sessions,
        r.unverified,
        r.retrospective,
        r.by_design,
        r.untradable,
        r.missing_bars,
    ) == (0, 0, 0, {}, {}, {})
