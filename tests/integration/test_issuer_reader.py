from datetime import UTC, date, datetime
from decimal import Decimal as D

import pytest

from algo.data.issuer_series import IdentityError
from algo.data.reader import BarReader
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from tests.integration.test_reader import action, bar

pytestmark = pytest.mark.integration
CHANGE = date(2024, 1, 5)  # ISIN change and 10:1 split, ex-date
PRE = [(date(2024, 1, 2), D(20000)), (date(2024, 1, 3), D(20100)), (date(2024, 1, 4), D(20200))]
POST = [(date(2024, 1, 5), D(2030)), (date(2024, 1, 8), D(2040))]
FIRST, LAST = date(2024, 1, 2), date(2024, 1, 8)


def build(conn, *, migrated: bool, link: bool = True):
    """Two ISINs of one issuer. migrated=False: everything on the new ISIN (today's layout).
    migrated=True: pre-change bars and actions on the old ISIN (the proposed layout)."""
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    old, new = repo.add_instrument(x, "NESTLEOLD"), repo.add_instrument(x, "NESTLEIND")
    owner_pre = old if migrated else new
    for d, c in PRE:
        bar(conn, owner_pre, d, c)
    for d, c in POST:
        bar(conn, new, d, c)
    action(conn, owner_pre, date(2023, 6, 1), "dividend", amount=D(75))
    action(conn, new, CHANGE, "split", num=D(10), den=D(1))
    if link:
        conn.execute(
            "INSERT INTO corporate_action_relationship (relationship_type, source_instrument_id,"
            " target_instrument_id, target_symbol, effective_date, evidence, review_decision_id,"
            " recorded_at) VALUES ('SAME_ISSUER_ISIN_CHANGE', %s, %s, 'NESTLEIND', %s,"
            " '[\"NSE circular CML60084\"]'::jsonb, 15, now())",
            (old, new, CHANGE),
        )
    return old, new, BarReader(conn)


def test_the_issuer_series_is_identical_under_todays_layout_and_the_proposed_one(conn):
    old, new, rd = build(conn, migrated=True)
    proposed = rd.issuer_history(new, FIRST, LAST, adjust="split")
    # the layout of today: everything on the new ISIN, no link
    conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    _, new2, rd2 = build(conn, migrated=False, link=False)
    today = rd2.history(new2, FIRST, LAST, adjust="split")
    assert [b.close for b in proposed.bars] == [b.close for b in today.bars]
    assert [b.close for b in proposed.bars] == [D(2000), D(2010), D(2020), D(2030), D(2040)]
    assert [b.volume for b in proposed.bars] == [b.volume for b in today.bars]
    assert [b.factor for b in proposed.bars] == [b.factor for b in today.bars]
    assert proposed.adjustment_version == today.adjustment_version  # same action history, pinned
    assert old != new


def test_an_instrument_read_never_mixes_in_the_other_isin_and_bars_keep_their_owner(conn):
    old, new, rd = build(conn, migrated=True)
    only_new = rd.history(new, FIRST, LAST)
    only_old = rd.history(old, FIRST, LAST)
    assert [b.close for b in only_new.bars] == [
        D(2030),
        D(2040),
    ]  # same issuer is NOT same instrument
    assert [b.close for b in only_old.bars] == [D(20000), D(20100), D(20200)]
    assert {b.owner for b in only_new.bars} == {new} and {b.owner for b in only_old.bars} == {old}
    from_new = rd.issuer_history(new, FIRST, LAST)
    from_old = rd.issuer_history(old, FIRST, LAST)
    assert [b.close for b in from_new.bars] == [b.close for b in from_old.bars]  # one issuer series
    assert [b.owner for b in from_new.bars] == [old, old, old, new, new]  # raw identity preserved
    assert [b.factor for b in from_new.bars] == [D(1)] * 5  # raw mode: nothing adjusted


def test_the_issuer_series_up_to_the_change_does_not_depend_on_later_information(conn):
    old, new, rd = build(conn, migrated=True)
    as_of = datetime(
        2024, 1, 4, 14, 0, tzinfo=UTC
    )  # 4 Jan bar published (13:00 UTC), split not yet known
    full = rd.issuer_history(new, FIRST, date(2024, 1, 4), adjust="split", as_of=as_of)
    conn.execute(
        "DELETE FROM bar_1d WHERE ts::date >= %s", (CHANGE,)
    )  # drop everything from 5 Jan on
    conn.execute("DELETE FROM corporate_action WHERE ex_date >= %s", (CHANGE,))
    prefix = rd.issuer_history(new, FIRST, date(2024, 1, 4), adjust="split", as_of=as_of)
    assert [b.close for b in full.bars] == [b.close for b in prefix.bars] == [c for _, c in PRE]
    assert [b.factor for b in full.bars] == [b.factor for b in prefix.bars]
    assert full.adjustment_version == prefix.adjustment_version
    # and the split is not applied before it is knowable (ex-date proxy): prices stay as traded
    assert [b.factor for b in full.bars] == [D(1)] * 3
    assert old != new


def test_a_link_with_data_still_on_the_new_isin_is_refused_not_guessed(conn):
    _, new, rd = build(conn, migrated=False)  # link present but nothing moved yet
    with pytest.raises(IdentityError, match="outside its interval"):
        rd.issuer_history(new, FIRST, LAST)
    assert len(rd.history(new, FIRST, LAST).bars) == 5  # the instrument read is unaffected


def test_without_links_the_issuer_read_is_the_instrument_read_and_a_missing_table_is_tolerated(
    conn,
):
    _, new, rd = build(conn, migrated=False, link=False)
    a = rd.issuer_history(new, FIRST, LAST, adjust="split")
    b = rd.history(new, FIRST, LAST, adjust="split")
    assert [x.close for x in a.bars] == [x.close for x in b.bars]
    assert rd.isin_links() == []
    conn.execute(
        "DROP TABLE security_conversion"
    )  # the later table that points at it (migration 025)
    conn.execute("DROP TABLE corporate_action_relationship")  # a database before migration 024
    assert rd.isin_links() == []
    assert len(rd.issuer_history(new, FIRST, LAST).bars) == 5
