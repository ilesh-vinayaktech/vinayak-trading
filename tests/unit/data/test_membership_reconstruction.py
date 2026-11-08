from datetime import date

import pytest

from algo.data.membership_reconstruction import (
    Transition,
    block_windows,
    combine_rows,
    entity_of,
    intervals_from,
    reconcile,
    union_events,
    walk_back,
)

D = date
START, ANCHOR = D(2020, 10, 1), D(2026, 11, 7)


def t(comp, ent, action, eff, ann=None, **kw):
    return Transition(comp, ent, ent.split(":")[1], action, eff, ann or D(2020, 1, 1), kw.get("doc", "d1"),
                      "sec", "h", "6", 1)  # fmt: skip


def test_entity_keys_never_confuse_instruments_symbols_and_placeholders():
    assert entity_of(7, "X", "MAPPED") == "i:7"
    assert entity_of(None, "PEL", "UNMAPPED_SYMBOL") == "s:PEL"
    assert entity_of(None, "DUMMYSIEMS", "PLACEHOLDER_SECURITY") == "p:DUMMYSIEMS"


def test_walk_back_undoes_each_transition_from_the_anchor():
    anchor = {"N50": frozenset({"i:1", "i:3"})}
    trs = [t("N50", "i:3", "INCLUDED", D(2023, 3, 31)), t("N50", "i:2", "EXCLUDED", D(2023, 3, 31)),
           t("N50", "i:1", "INCLUDED", D(2021, 3, 31)), t("N50", "i:9", "EXCLUDED", D(2021, 3, 31))]  # fmt: skip
    w = walk_back(anchor, trs, START, ANCHOR)
    assert [s.day for s in w.steps] == [D(2021, 3, 31), D(2023, 3, 31)]
    assert w.steps[1].before["N50"] == {"i:1", "i:2"} and w.steps[1].after["N50"] == {"i:1", "i:3"}
    assert w.steps[0].before["N50"] == {"i:2", "i:9"}
    assert w.initial["N50"] == {"i:2", "i:9"}
    assert not w.discrepancies


def test_inconsistent_history_is_flagged_never_forced():
    anchor = {"N50": frozenset({"i:1"})}
    trs = [
        t("N50", "i:5", "INCLUDED", D(2022, 3, 31)),  # not a member afterwards
        t("N50", "i:1", "EXCLUDED", D(2022, 3, 31)),
    ]  # still a member afterwards
    w = walk_back(anchor, trs, START, ANCHOR)
    kinds = sorted(d["kind"] for d in w.discrepancies)
    assert kinds == ["EXCLUDED_BUT_MEMBER_AFTER", "INCLUDED_BUT_NOT_MEMBER_AFTER"]
    assert w.initial["N50"] == {"i:1"}  # counts are whatever the evidence yields


def test_same_day_include_and_exclude_of_one_entity_is_flagged():
    w = walk_back({"N50": frozenset({"i:1"})}, [t("N50", "i:1", "INCLUDED", D(2022, 3, 31)), t("N50", "i:1", "EXCLUDED", D(2022, 3, 31))], START, ANCHOR)  # fmt: skip
    assert "SAME_DAY_BOTH" in {d["kind"] for d in w.discrepancies}


def test_undated_future_and_pre_window_transitions_are_not_applied():
    anchor = {"N50": frozenset({"i:1"})}
    trs = [t("N50", "i:2", "INCLUDED", None), t("N50", "i:3", "INCLUDED", D(2027, 1, 1)),
           t("N50", "i:4", "INCLUDED", D(2020, 3, 27)), t("N50", "i:5", "INCLUDED", START),
           t("OTHER", "i:6", "INCLUDED", D(2022, 1, 1))]  # fmt: skip
    w = walk_back(anchor, trs, START, ANCHOR)
    assert not w.steps and w.initial["N50"] == {"i:1"}
    assert [x.entity for x in w.unplaced] == ["i:2"]
    assert [x.entity for x in w.future] == ["i:3"]


def test_union_events_ignore_moves_between_components():
    anchor = {
        "N50": frozenset({"i:1", "i:2"}),
        "NEXT": frozenset({"i:3"}),
        "MID": frozenset({"i:4"}),
    }
    trs = [t("N50", "i:2", "INCLUDED", D(2022, 3, 31)), t("NEXT", "i:2", "EXCLUDED", D(2022, 3, 31)),  # a move up
           t("NEXT", "i:3", "INCLUDED", D(2022, 3, 31)), t("MID", "i:3", "EXCLUDED", D(2022, 3, 31)),  # a move up
           t("MID", "i:4", "INCLUDED", D(2023, 3, 31), D(2023, 3, 1)), t("MID", "i:8", "EXCLUDED", D(2023, 3, 31), D(2023, 3, 1))]  # fmt: skip
    w = walk_back(anchor, trs, START, ANCHOR)
    ev = union_events(w, ["N50", "NEXT", "MID"])
    assert [(e.day, e.entity, e.kind) for e in ev] == [
        (D(2023, 3, 31), "i:4", "ADD"),
        (D(2023, 3, 31), "i:8", "REMOVE"),
    ]
    assert ev[0].announced == D(2023, 3, 1) and ev[0].sources[0].doc_id == "d1"


def test_intervals_start_at_the_window_and_close_on_removal():
    anchor = {"N": frozenset({"i:1", "i:4"})}
    trs = [t("N", "i:4", "INCLUDED", D(2023, 3, 31)), t("N", "i:2", "EXCLUDED", D(2023, 3, 31))]
    w = walk_back(anchor, trs, START, ANCHOR)
    iv = intervals_from(w, ["N"], START, ANCHOR)
    assert [(i.entity, i.start, i.end, i.start_basis) for i in iv] == [
        ("i:1", START, None, "WINDOW_START_BACKWARD_WALK"),
        ("i:2", START, D(2023, 3, 31), "WINDOW_START_BACKWARD_WALK"),
        ("i:4", D(2023, 3, 31), None, "EVENT"),
    ]


def test_reconcile_reports_differences_per_snapshot_without_forcing_agreement():
    anchor = {"N": frozenset({"i:1", "i:2"})}
    w = walk_back(anchor, [t("N", "i:2", "INCLUDED", D(2022, 3, 31))], START, ANCHOR)
    snaps = {D(2021, 1, 29): frozenset({"i:1", "i:7"}), D(2022, 4, 29): frozenset({"i:1", "i:2"})}
    r = reconcile(w, ["N"], snaps)
    assert r[0] == {"date": D(2021, 1, 29), "snapshot": 2, "reconstructed": 1, "only_in_snapshot": ["i:7"], "only_in_reconstruction": [], "common": ["i:1"], "coverage": "FULL"}  # fmt: skip
    assert r[1]["only_in_snapshot"] == [] and r[1]["only_in_reconstruction"] == []


def test_block_windows_are_bounded_by_the_nearest_agreeing_snapshots():
    rec = [
        {"date": D(2021, 1, 29), "only_in_snapshot": [], "only_in_reconstruction": []},
        {"date": D(2021, 2, 26), "only_in_snapshot": ["i:7"], "only_in_reconstruction": []},
        {"date": D(2021, 3, 31), "only_in_snapshot": ["i:7"], "only_in_reconstruction": []},
        {"date": D(2021, 4, 30), "only_in_snapshot": [], "only_in_reconstruction": []},
        {"date": D(2022, 1, 31), "only_in_snapshot": [], "only_in_reconstruction": ["i:9"]},
    ]
    bw = block_windows(rec, START, ANCHOR)
    assert bw == {"i:7": [(D(2021, 1, 30), D(2021, 4, 30))], "i:9": [(D(2021, 5, 1), ANCHOR)]}


def test_block_window_for_an_entity_that_never_agrees_spans_the_whole_window():
    rec = [{"date": D(2021, 1, 29), "only_in_snapshot": ["i:7"], "only_in_reconstruction": []}]
    assert block_windows(rec, START, ANCHOR) == {"i:7": [(START, ANCHOR)]}


def test_reconcile_requires_snapshots_inside_the_window():
    anchor = {"N": frozenset({"i:1"})}
    w = walk_back(anchor, [], START, ANCHOR)
    assert reconcile(w, ["N"], {D(2019, 1, 1): frozenset({"i:1"})}) == []
    with pytest.raises(KeyError):
        reconcile(w, ["MISSING"], {D(2021, 1, 1): frozenset()})


def test_intervals_ignore_events_after_the_requested_end():
    w = walk_back(
        {"N": frozenset({"i:1"})}, [t("N", "i:1", "INCLUDED", D(2023, 3, 31))], START, ANCHOR
    )
    assert [(i.entity, i.end) for i in intervals_from(w, ["N"], START, D(2022, 1, 1))] == []


def test_a_partial_snapshot_is_silent_about_an_entity_absent_from_both_sides():
    full = {"only_in_snapshot": [], "only_in_reconstruction": [], "common": [], "coverage": "FULL"}
    part = {
        "only_in_snapshot": [],
        "only_in_reconstruction": [],
        "common": [],
        "coverage": "PARTIAL",
    }
    rec = [
        {**full, "date": D(2021, 1, 29), "only_in_reconstruction": ["i:7"]},
        {**part, "date": D(2021, 2, 26)},  # i:7 absent from both: proves nothing
        {**part, "date": D(2021, 3, 31), "common": ["i:7"]},  # both sides have it: agreement
        {**part, "date": D(2021, 4, 30), "common": ["i:7"]},
    ]
    assert block_windows(rec, START, ANCHOR) == {"i:7": [(START, D(2021, 3, 31))]}
    only_partial = [
        {**part, "date": D(2021, 2, 26), "only_in_reconstruction": ["i:7"]},
        {**part, "date": D(2021, 3, 31)},
    ]
    assert block_windows(only_partial, START, ANCHOR) == {"i:7": [(START, ANCHOR)]}


def test_combine_rows_prefers_the_full_comparison_on_a_shared_date():
    f = [{"date": D(2021, 1, 29), "coverage": "FULL"}]
    p = [
        {"date": D(2021, 1, 29), "coverage": "PARTIAL"},
        {"date": D(2021, 2, 26), "coverage": "PARTIAL"},
    ]
    assert [(r["date"], r["coverage"]) for r in combine_rows(f, p)] == [
        (D(2021, 1, 29), "FULL"),
        (D(2021, 2, 26), "PARTIAL"),
    ]
