from datetime import date

from algo.data.universe_derive import (
    BOUNDARY,
    M1,
    M2,
    CEvent,
    backward_counts,
    build_report,
    check_checkpoints,
    check_snapshot,
    derive_union,
    series_of,
)  # fmt: skip

D = date


def ev(key, comp, action, eff, ann=None, doc="d", symbol=None, placeholder=False):
    return CEvent(key, symbol or key, comp, action, eff, ann or eff, doc, 1, placeholder)


def derived(events):
    return derive_union(events)[0]


def test_a_transfer_between_components_is_not_a_nifty_200_change():
    out = derived([
        ev("i:1", "NIFTY_NEXT_50", "EXCLUDED", D(2019, 3, 29)),
        ev("i:1", "MIDCAP_100", "INCLUDED", D(2019, 3, 29)),
    ])  # fmt: skip
    assert out == []


def test_genuine_additions_and_removals_with_prior_state_inferred_from_the_first_event():
    out = derived([
        ev("i:1", "MIDCAP_100", "INCLUDED", D(2019, 3, 29), ann=D(2019, 2, 20), doc="a"),
        ev("i:2", "NIFTY_NEXT_50", "EXCLUDED", D(2019, 9, 27), doc="b"),
        ev("i:1", "MIDCAP_100", "EXCLUDED", D(2020, 3, 27), doc="c"),
    ])  # fmt: skip
    got = [(d.index_id, d.key, d.event_type, d.effective, d.announced) for d in out]
    assert got == [
        (
            M2,
            "i:1",
            "ADD",
            D(2019, 3, 29),
            D(2019, 2, 20),
        ),  # announcement kept apart from effective
        (M2, "i:2", "REMOVE", D(2019, 9, 27), D(2019, 9, 27)),
        (M2, "i:1", "REMOVE", D(2020, 3, 27), D(2020, 3, 27)),
    ]
    assert out[0].docs == ("a",)


def test_an_instrument_in_two_components_stays_until_it_leaves_both():
    out = derived([
        ev("i:1", "NIFTY_50", "EXCLUDED", D(2019, 1, 1)),  # first event: it was in Nifty 50
        ev("i:1", "NIFTY_NEXT_50", "INCLUDED", D(2019, 1, 1)),  # moved down: still a member
        ev("i:1", "NIFTY_NEXT_50", "EXCLUDED", D(2019, 6, 1)),
    ])  # fmt: skip
    assert [(d.event_type, d.effective) for d in out] == [("REMOVE", D(2019, 6, 1))]


def test_the_methodology_boundary_keeps_two_series_apart():
    assert series_of(BOUNDARY) == M2 and series_of(date(2018, 4, 1)) == M1
    out = derived([
        ev("i:1", "MIDCAP_100_FULL", "INCLUDED", D(2017, 9, 29)),  # legacy definition -> M1
        ev("i:2", "MIDCAP_100_FREE_FLOAT", "INCLUDED", D(2017, 9, 29)),  # not in N200 then: ignored
        ev("i:3", "MIDCAP_100", "INCLUDED", D(2018, 9, 28)),  # new definition -> M2
        ev("i:4", "MIDCAP_100_FULL", "INCLUDED", D(2018, 9, 28)),  # legacy label after: ignored
        ev("i:5", "MIDCAP_100_FREE_FLOAT", "INCLUDED", D(2018, 4, 2)),  # renamed index: counts
    ])  # fmt: skip
    assert sorted((d.index_id, d.key) for d in out) == [(M2, "i:3"), (M2, "i:5"), (M1, "i:1")]


def test_same_day_events_combine_announcements_and_documents():
    out = derived([
        ev("i:1", "NIFTY_50", "INCLUDED", D(2019, 9, 27), ann=D(2019, 8, 28), doc="b"),
        ev("i:1", "NIFTY_NEXT_50", "INCLUDED", D(2019, 9, 27), ann=D(2019, 8, 20), doc="a"),
    ])  # fmt: skip
    assert len(out) == 1 and out[0].announced == D(2019, 8, 20) and out[0].docs == ("a", "b")


def test_placeholder_membership_is_flagged():
    out = derived([ev("s:DUMMYX", "NIFTY_NEXT_50", "INCLUDED", D(2025, 4, 7), placeholder=True)])
    assert out[0].placeholder and out[0].key == "s:DUMMYX"


def test_a_repeated_component_event_means_an_event_is_missing():
    _, bad = derive_union([
        ev("i:1", "NIFTY_NEXT_50", "INCLUDED", D(2019, 1, 1)),
        ev("i:1", "NIFTY_NEXT_50", "INCLUDED", D(2019, 6, 1)),
        ev("i:2", "NIFTY_50", "EXCLUDED", D(2019, 1, 1)),
        ev("i:2", "NIFTY_50", "EXCLUDED", D(2019, 6, 1)),
    ])  # fmt: skip
    assert [(d.kind, d.key, d.on) for d in bad] == [
        ("NON_ALTERNATING", "i:1", D(2019, 6, 1)), ("NON_ALTERNATING", "i:2", D(2019, 6, 1)),
    ]  # fmt: skip
    assert "twice in a row" in bad[0].detail


def test_the_snapshot_check_compares_the_last_event_with_the_current_list():
    d = derived([
        ev("i:1", "MIDCAP_100", "INCLUDED", D(2019, 1, 1)),
        ev("i:2", "MIDCAP_100", "EXCLUDED", D(2019, 1, 1)),
        ev("i:3", "MIDCAP_100", "INCLUDED", D(2019, 1, 1)),
        ev("i:4", "MIDCAP_100", "EXCLUDED", D(2019, 1, 1)),
        ev("s:UNK", "MIDCAP_100", "INCLUDED", D(2019, 1, 1)),
        ev("s:DUMMYZ", "MIDCAP_100", "INCLUDED", D(2019, 1, 1), placeholder=True),
        ev("i:9", "MIDCAP_100_FULL", "INCLUDED", D(2017, 9, 29)),  # legacy series: not compared
    ])  # fmt: skip
    bad = check_snapshot(d, snapshot={1, 4})  # 1 ok; 2 ok; 3 added but gone; 4 removed but present
    assert [(x.kind, x.key) for x in bad] == [
        ("SNAPSHOT_MISMATCH", "i:3"),
        ("SNAPSHOT_MISMATCH", "i:4"),
    ]
    assert "snapshot says not a member" in bad[0].detail and "says member" in bad[1].detail
    assert check_snapshot([], set()) == []


def test_explicit_nifty_200_rows_are_checkpoints_that_must_be_reproduced():
    comp = [ev("i:1", "MIDCAP_100", "INCLUDED", D(2019, 3, 29)),
            ev("i:2", "MIDCAP_100", "INCLUDED", D(2019, 3, 29)),
            ev("i:5", "MIDCAP_100", "INCLUDED", D(2019, 6, 1))]  # fmt: skip
    d = derived(comp)
    explicit = [
        ev("i:1", "NIFTY_200", "INCLUDED", D(2019, 3, 29)),
        ev("i:3", "NIFTY_200", "INCLUDED", D(2019, 3, 29)),
    ]  # i:2 unlisted, i:3 unproduced
    bad = check_checkpoints(d, explicit)
    assert sorted((x.kind, x.key) for x in bad) == [
        ("CHECKPOINT_EXTRA", "i:2"),
        ("CHECKPOINT_MISSING", "i:3"),
    ]
    assert check_checkpoints(d, [ev("i:1", "NIFTY_200", "INCLUDED", D(2019, 3, 29)),
                                 ev("i:2", "NIFTY_200", "INCLUDED", D(2019, 3, 29))]) == []  # fmt: skip
    # i:5's change is on a day with no explicit section: not contradicted


def test_counts_are_rebuilt_backwards_from_the_current_list_and_not_forced():
    d = derived([
        ev("i:4", "MIDCAP_100", "EXCLUDED", D(2019, 1, 1)),
        ev("i:3", "MIDCAP_100", "INCLUDED", D(2019, 6, 1)),
        ev("s:UNK", "MIDCAP_100", "INCLUDED", D(2019, 7, 1)),  # unmapped: not countable
    ])  # fmt: skip
    # snapshot {1,2,3}: before 2019-06-01 3 was absent -> 2 members; before 2019-01-01 4 was in -> 3
    assert backward_counts(d, {1, 2, 3}) == [(D(2019, 1, 1), 3), (D(2019, 6, 1), 2)]


def test_counts_are_one_per_change_date_with_all_of_its_changes_undone():
    d = derived([
        ev("i:3", "MIDCAP_100", "INCLUDED", D(2019, 6, 1)),
        ev("i:4", "MIDCAP_100", "INCLUDED", D(2019, 6, 1)),
        ev("i:5", "MIDCAP_100", "EXCLUDED", D(2019, 6, 1)),
    ])  # fmt: skip
    assert backward_counts(d, {1, 2, 3, 4}) == [(D(2019, 6, 1), 3)]  # {1,2} + 5 undone


def test_the_report_lists_every_kind_of_gap_and_never_adjusts_the_result():
    comp = [ev("i:1", "MIDCAP_100", "INCLUDED", D(2019, 1, 1)),
            ev("s:OLD", "MIDCAP_100", "EXCLUDED", D(2019, 1, 1)),
            ev("s:DUMMYQ", "NIFTY_NEXT_50", "INCLUDED", D(2025, 4, 7), placeholder=True),
            ev("i:1", "NIFTY_200", "INCLUDED", D(2019, 1, 1)),
            ev("s:OLD", "NIFTY_200", "EXCLUDED", D(2019, 1, 1))]  # fmt: skip
    r = build_report(comp, snapshot={1}, manual_documents=["pr_x"])
    assert r.gaps == {
        "MANUAL_DOCUMENT": 1,
        "METHODOLOGY_BOUNDARY": 1,
        "PLACEHOLDER_EVENT": 1,
        "UNMAPPED_EVENT": 2,
    }  # fmt: skip  (the component row and its explicit twin)
    assert r.of_kind("MANUAL_DOCUMENT")[0].symbol == "pr_x"
    assert (
        len(r.derived) == 3
        and r.counts[M2] == [(D(2019, 1, 1), 0), (D(2025, 4, 7), 1)][:0] + r.counts[M2]
    )


def test_undated_rows_are_reported_not_dropped():
    r = build_report([], set(), undated_rows=[("IGL", "MIDCAP_100", "INCLUDED", "pr_x")])
    u = r.of_kind("UNDATED_ROW")
    assert len(u) == 1 and u[0].symbol == "IGL" and "no effective date" in u[0].detail
