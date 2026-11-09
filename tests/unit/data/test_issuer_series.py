from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from algo.data.adjust.factors import ActionRecord
from algo.data.issuer_series import IdentityError, Link, Segment, chain, latest_of, stitch

D = date
OLD, NEW = 1, 2


def bar(day, price):  # a session opens 03:45 UTC = 09:15 IST
    return (datetime(day.year, day.month, day.day, 3, 45, tzinfo=UTC), *(Decimal(price),) * 5)


def action(ex, kind="split", num=1, den=10):
    return ActionRecord(
        ex, kind, "ok", Decimal(num), Decimal(den), None, datetime(2023, 12, 22, tzinfo=UTC)
    )


def test_without_a_link_an_instrument_is_its_own_chain_and_passes_through():
    assert chain([], NEW) == [Segment(NEW, None, None)]
    rows = {NEW: [bar(D(2024, 1, 5), 100)]}
    got = stitch(chain([], NEW), rows, {NEW: [action(D(2024, 1, 5))]})
    assert got == (rows[NEW], [NEW], [action(D(2024, 1, 5))])


def test_an_isin_change_makes_two_end_exclusive_segments_found_from_either_end():
    link = Link(OLD, NEW, D(2024, 1, 5))
    want = [Segment(OLD, None, D(2024, 1, 5)), Segment(NEW, D(2024, 1, 5), None)]
    assert chain([link], OLD) == want == chain([link], NEW)  # same issuer series from either end
    third = Link(NEW, 3, D(2025, 1, 1))
    assert [s.instrument_id for s in chain([link, third], OLD)] == [OLD, NEW, 3]
    assert chain([link], 99) == [Segment(99, None, None)]  # an unrelated instrument is untouched


def test_each_instrument_owns_only_its_own_interval_and_keeps_its_identity():
    link = Link(OLD, NEW, D(2024, 1, 5))
    rows = {
        OLD: [bar(D(2024, 1, 3), 20000), bar(D(2024, 1, 4), 20100)],
        NEW: [bar(D(2024, 1, 5), 2000)],
    }
    recs = {OLD: [action(D(2023, 6, 1), "dividend")], NEW: [action(D(2024, 1, 5))]}
    out_rows, owners, out_recs = stitch(chain([link], NEW), rows, recs)
    assert [r[1] for r in out_rows] == [20000, 20100, 2000] and owners == [OLD, OLD, NEW]
    assert [a.kind for a in out_recs] == [
        "dividend",
        "split",
    ]  # the issuer's action history is continuous
    # the split is on both instruments in the feed: counted once
    both = stitch(
        chain([link], NEW), rows, {OLD: [action(D(2024, 1, 5))], NEW: [action(D(2024, 1, 5))]}
    )
    assert len(both[2]) == 1


def test_data_that_does_not_match_the_identity_is_refused_never_guessed():
    link = Link(OLD, NEW, D(2024, 1, 5))
    c = chain([link], NEW)
    early_on_new = {
        OLD: [],
        NEW: [bar(D(2024, 1, 4), 1)],
    }  # not migrated: a pre-change bar is on the new ISIN
    with pytest.raises(IdentityError, match="outside its interval"):
        stitch(c, early_on_new, {OLD: [], NEW: []})
    late_on_old = {OLD: [bar(D(2024, 1, 5), 1)], NEW: []}
    with pytest.raises(IdentityError, match="outside its interval"):
        stitch(c, late_on_old, {OLD: [], NEW: []})


def test_two_owners_for_one_session_is_refused():
    a = Segment(OLD, None, None)
    b = Segment(NEW, None, None)  # overlapping intervals (an invalid chain built by hand)
    dup = {OLD: [bar(D(2024, 1, 4), 1)], NEW: [bar(D(2024, 1, 4), 1)]}
    with pytest.raises(IdentityError, match="same session"):
        stitch([a, b], dup, {OLD: [], NEW: []})


def test_ambiguous_links_are_refused():
    with pytest.raises(IdentityError, match="ambiguous"):
        chain([Link(OLD, NEW, D(2024, 1, 5)), Link(OLD, 3, D(2024, 1, 5))], OLD)
    with pytest.raises(IdentityError, match="ambiguous"):
        chain([Link(OLD, NEW, D(2024, 1, 5)), Link(3, NEW, D(2024, 1, 5))], NEW)
    with pytest.raises(IdentityError, match="ambiguous"):
        chain([Link(OLD, OLD, D(2024, 1, 5))], OLD)
    with pytest.raises(IdentityError, match="cycle"):
        chain([Link(OLD, NEW, D(2024, 1, 5)), Link(NEW, OLD, D(2025, 1, 5))], OLD)


def test_every_superseded_isin_maps_to_the_latest_of_its_issuer_and_nothing_else_does():
    links = [
        Link(OLD, NEW, D(2024, 1, 5)),
        Link(NEW, 3, D(2025, 1, 1)),
        Link(10, 11, D(2020, 1, 1)),
    ]
    assert latest_of(links) == {OLD: 3, NEW: 3, 10: 11}  # the latest ISINs (3, 11) are not keys
    assert latest_of([]) == {}
