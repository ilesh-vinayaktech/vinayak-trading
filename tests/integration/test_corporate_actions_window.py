"""The daily whole-market window: past and today's actions join the real table, announced future ones
live in `corporate_action_upcoming` (replaced every day, so a revised date never leaves a stale copy)."""

import json
from datetime import UTC, date, datetime

import pytest

from algo.data.corporate_actions import load_window, new_unresolved, review_keys
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
TODAY = date(2026, 11, 13)
NOW = datetime(2026, 11, 13, 13, 0, tzinfo=UTC)


def raw(*rows):
    """NSE's answer for a date range: one row per announcement, for any company."""
    return json.dumps(
        [{"symbol": s, "series": "EQ", "subject": sub, "exDate": ex, "recDate": ex, "isin": "INE000000000"}
         for s, sub, ex in rows]
    ).encode()  # fmt: skip


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    ids = {}
    for s in ("RELIANCE", "TCS", "ITC"):
        ids[s] = repo.add_instrument(x, s)
        repo.add_alias(ids[s], "nse", s, date(1990, 1, 1))
    return conn, ids


def counts(conn):
    n = conn.execute("SELECT count(*) FROM corporate_action").fetchone()[0]
    u = conn.execute("SELECT count(*) FROM corporate_action_upcoming").fetchone()[0]
    return n, u


def test_past_and_todays_actions_join_the_real_table_and_future_ones_wait_in_upcoming(env):
    conn, ids = env
    window = raw(
        ("RELIANCE", "Interim Dividend - Rs 5 Per Share", "10-Nov-2026"),
        ("TCS", "Interim Dividend - Rs 9 Per Share", "13-Nov-2026"),  # today: it has happened
        ("ITC", "Interim Dividend - Rs 7 Per Share", "20-Nov-2026"),  # announced, not yet
    )
    r = load_window(conn, window, TODAY, "sum", NOW)
    assert (r.inserted, r.upcoming) == (2, 1) and r.unknown_symbols == []
    assert counts(conn) == (2, 1)
    up = conn.execute(
        "SELECT instrument_id, ex_date, kind, amount FROM corporate_action_upcoming"
    ).fetchall()
    assert [(i, str(d), k, int(a)) for i, d, k, a in up] == [
        (ids["ITC"], "2026-11-20", "dividend", 7)
    ]


def test_running_the_same_window_again_changes_nothing(env):
    conn, _ = env
    window = raw(
        ("RELIANCE", "Interim Dividend - Rs 5 Per Share", "10-Nov-2026"),
        ("ITC", "Interim Dividend - Rs 7 Per Share", "20-Nov-2026"),
    )
    load_window(conn, window, TODAY, "sum", NOW)
    again = load_window(conn, window, TODAY, "sum", NOW)
    assert (again.inserted, again.unchanged, again.upcoming) == (0, 1, 1)
    assert counts(conn) == (1, 1)


def test_a_revised_date_replaces_the_old_one_and_never_reaches_the_real_table(env):
    conn, _ = env
    load_window(
        conn, raw(("ITC", "Interim Dividend - Rs 7 Per Share", "20-Nov-2026")), TODAY, "a", NOW
    )
    revised = raw(("ITC", "Interim Dividend - Rs 7 Per Share (Purpose Revised)", "24-Nov-2026"))
    load_window(conn, revised, date(2026, 11, 14), "b", NOW)
    rows = conn.execute("SELECT ex_date FROM corporate_action_upcoming").fetchall()
    assert [str(r[0]) for r in rows] == ["2026-11-24"]  # only the new date; the old one is gone
    assert counts(conn)[0] == 0  # nothing about it was ever written to the real table


def test_when_the_ex_date_arrives_the_action_moves_from_upcoming_to_the_real_table(env):
    conn, _ = env
    window = raw(("ITC", "Interim Dividend - Rs 7 Per Share", "20-Nov-2026"))
    load_window(conn, window, TODAY, "a", NOW)
    assert counts(conn) == (0, 1)
    load_window(
        conn, window, date(2026, 11, 20), "b", NOW
    )  # the daily window still lists it that day
    assert counts(conn) == (1, 0)


def test_unknown_companies_are_reported_and_new_review_items_are_found(env):
    conn, _ = env
    before = review_keys(conn)
    window = raw(
        ("NOSUCHCO", "Interim Dividend - Rs 1 Per Share", "10-Nov-2026"),
        ("RELIANCE", "Demerger", "12-Nov-2026"),  # a person has to decide this one
    )
    r = load_window(conn, window, TODAY, "sum", NOW)
    assert r.unknown_symbols == ["NOSUCHCO"] and r.inserted == 1
    assert [(s, k) for s, _ex, k, _subj in new_unresolved(conn, before)] == [
        ("RELIANCE", "demerger")
    ]
