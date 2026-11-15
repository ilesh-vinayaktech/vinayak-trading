from datetime import date, timedelta

import pytest

from algo.data.membership_reconstruction import (
    Interval,
    Replacement,
    Revocation,
    Transition,
    Void,
    apply_replacements,
    apply_revocations,
    apply_voids,
    block_windows,
    closing_entity,
    combine_rows,
    entity_of,
    equivalence_map,
    hand_over_isin_changes,
    hand_over_spans,
    intervals_from,
    reconcile,
    state_on,
    unify_entities,
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


def test_an_exclusion_that_names_its_dummy_closes_the_placeholder_not_a_new_entity():
    # the same release says: listing ITCHOTELS replaces dummy DUMMYITC. Entities are NOT merged; the
    # exclusion simply ends the membership that the placeholder began.
    assert closing_entity(7, "ITCHOTELS", "MAPPED", "DUMMYITC", "EXCLUDED") == "p:DUMMYITC"
    assert (
        closing_entity(None, "TMCV", "UNMAPPED_SYMBOL", "DUMMYTATAM", "EXCLUDED") == "p:DUMMYTATAM"
    )


def test_closing_entity_falls_back_to_the_ordinary_key():
    assert closing_entity(7, "X", "MAPPED", None, "EXCLUDED") == "i:7"  # no related symbol
    assert closing_entity(7, "X", "MAPPED", "DUMMYX", "INCLUDED") == "i:7"  # only exclusions close
    assert closing_entity(7, "X", "MAPPED", "OTHER", "EXCLUDED") == "i:7"  # not a dummy symbol
    assert closing_entity(None, "DUMMYX", "PLACEHOLDER_SECURITY", None, "INCLUDED") == "p:DUMMYX"


def test_a_placeholder_included_then_closed_leaves_no_phantom_membership():
    trs = [t("N50", "p:DUMMYITC", "INCLUDED", D(2025, 1, 6)),
           t("N50", "p:DUMMYITC", "EXCLUDED", D(2025, 2, 10))]  # fmt: skip
    w = walk_back({"N50": frozenset({"i:1"})}, trs, START, ANCHOR)
    assert not w.discrepancies
    assert w.initial["N50"] == {
        "i:1"
    }  # neither the placeholder nor the listing is a member at the start


def test_a_listing_replaces_its_placeholder_without_merging_the_two_entities():
    # DUMMYITC (placeholder) is a member from 6 Jan; ITCHOTELS lists on 29 Jan and is excluded 10 Feb
    trs = [t("N50", "p:DUMMYITC", "INCLUDED", D(2025, 1, 6), doc="inc"),
           t("N200x", "p:DUMMYITC", "INCLUDED", D(2025, 1, 6), doc="inc"),
           t("N50", "i:7", "EXCLUDED", D(2025, 2, 10), doc="exc"),
           t("N200x", "i:7", "EXCLUDED", D(2025, 2, 10), doc="exc")]  # fmt: skip
    rep = Replacement("DUMMYITC", "i:7", "ITCHOTELS", D(2025, 1, 29), "exc")
    out, unmatched = apply_replacements(trs, [rep])
    assert unmatched == []
    swaps = [x for x in out if x.doc_id == "exc" and x.section == "placeholder replacement"]
    assert {(x.component, x.entity, x.action, x.effective) for x in swaps} == {
        ("N50", "p:DUMMYITC", "EXCLUDED", D(2025, 1, 29)),
        ("N50", "i:7", "INCLUDED", D(2025, 1, 29)),
        ("N200x", "p:DUMMYITC", "EXCLUDED", D(2025, 1, 29)),
        ("N200x", "i:7", "INCLUDED", D(2025, 1, 29)),
    }
    assert len(out) == len(trs) + 4  # originals untouched, only the handover is added
    w = walk_back({"N50": frozenset(), "N200x": frozenset()}, out, START, ANCHOR)
    assert not w.discrepancies  # placeholder -> listing -> excluded is a consistent history
    assert w.initial == {"N50": frozenset(), "N200x": frozenset()}


def test_a_pre_alias_entity_can_hand_over_to_its_listing():
    # JIOFIN was in the indices from 20 Jul 2023 (symbol not yet alias-valid: entity s:JIOFIN) and
    # listed on 21 Aug; the exclusion on 7 Sep acts on the instrument i:5
    trs = [t("N50", "s:JIOFIN", "INCLUDED", D(2023, 7, 20), doc="inc"),
           t("N50", "i:5", "EXCLUDED", D(2023, 9, 7), doc="exc")]  # fmt: skip
    rep = Replacement("JIOFIN", "i:5", "JIOFIN", D(2023, 8, 21), "exc", "s:JIOFIN")
    out, unmatched = apply_replacements(trs, [rep])
    assert unmatched == []
    swaps = [x for x in out if x.section == "placeholder replacement"]
    assert {(x.entity, x.action) for x in swaps} == {("s:JIOFIN", "EXCLUDED"), ("i:5", "INCLUDED")}
    assert not walk_back({"N50": frozenset()}, out, START, ANCHOR).discrepancies


def test_the_handover_is_known_only_from_the_release_that_states_it_never_backdated():
    # listed 19 Jun, but the release stating it came out on 25 Jun: the handover is effective 19 Jun
    # yet its announcement (known_at) is 25 Jun
    trs = [t("N50", "p:DUMMYX", "INCLUDED", D(2025, 4, 7), ann=D(2025, 4, 2), doc="inc"),
           t("N50", "i:7", "EXCLUDED", D(2025, 6, 27), ann=D(2025, 6, 25), doc="exc")]  # fmt: skip
    out, _ = apply_replacements(trs, [Replacement("DUMMYX", "i:7", "X", D(2025, 6, 19), "exc")])
    swaps = [x for x in out if x.section == "placeholder replacement"]
    assert {x.effective for x in swaps} == {D(2025, 6, 19)}
    assert {x.announced for x in swaps} == {D(2025, 6, 25)}  # not 19 Jun, not the inclusion's date


def test_an_interval_ends_on_the_first_day_the_stock_is_not_a_member():
    trs = [t("N", "i:1", "INCLUDED", D(2025, 6, 23)), t("N", "i:1", "EXCLUDED", D(2025, 6, 27))]
    w = walk_back({"N": frozenset()}, trs, START, ANCHOR)
    (iv,) = intervals_from(w, ["N"], START, ANCHOR)
    assert (iv.start, iv.end) == (D(2025, 6, 23), D(2025, 6, 27))  # end is exclusive
    assert "i:1" in state_on(w, ["N"], D(2025, 6, 26))  # last member day
    assert "i:1" not in state_on(
        w, ["N"], D(2025, 6, 27)
    )  # the end date itself is not a member day
    assert "i:1" in state_on(w, ["N"], D(2025, 6, 23))  # the start date is a member day


def test_a_placeholder_equivalence_can_point_at_a_pre_listing_entity():
    # DUMMYREL (a monthly file's name) and s:JIOFIN (the release's) are one pre-listing entity
    assert equivalence_map([{"from": ["p:DUMMYREL"], "to": "s:JIOFIN"}]) == {
        "p:DUMMYREL": "s:JIOFIN"
    }


def test_a_replacement_with_nothing_to_hand_over_is_reported():
    inc = t("N50", "p:DUMMYX", "INCLUDED", D(2025, 1, 6))
    exc = t("N50", "i:7", "EXCLUDED", D(2025, 2, 10))
    no_exclusion = Replacement("DUMMYX", "i:8", "X", D(2025, 1, 29), "d")
    no_placeholder = Replacement("DUMMYNO", "i:7", "X", D(2025, 1, 29), "d")
    too_late = Replacement("DUMMYX", "i:7", "X", D(2025, 3, 1), "d")  # lists after the exclusion
    too_early = Replacement("DUMMYX", "i:7", "X", D(2025, 1, 1), "d")  # lists before the inclusion
    out, unmatched = apply_replacements(
        [inc, exc], [no_exclusion, no_placeholder, too_late, too_early]
    )
    assert out == [inc, exc]
    assert unmatched == [no_exclusion, no_placeholder, too_late, too_early]


def test_closing_entity_leaves_a_replaced_dummy_to_the_replacement():
    assert (
        closing_entity(7, "ITCHOTELS", "MAPPED", "DUMMYITC", "EXCLUDED", frozenset({"DUMMYITC"}))
        == "i:7"
    )
    assert (
        closing_entity(7, "ITCHOTELS", "MAPPED", "DUMMYITC", "EXCLUDED", frozenset())
        == "p:DUMMYITC"
    )


def test_a_revoked_inclusion_is_cancelled_not_compensated():
    inc = t("MID", "i:5", "INCLUDED", D(2024, 9, 30), doc="aug")
    other = t("MID", "i:6", "INCLUDED", D(2024, 9, 30), doc="aug")
    rv = Revocation("aug", "sep", "MID", "5", "INCLUDED", D(2024, 9, 30))
    kept, cancelled, unmatched = apply_revocations([inc, other], [rv])
    assert kept == [other] and cancelled == [(rv, inc)] and unmatched == []
    # the walk now sees no inclusion for i:5 at all, so it is not inconsistent
    w = walk_back({"MID": frozenset({"i:6"})}, kept, START, ANCHOR)
    assert not w.discrepancies


def test_a_revoked_exclusion_keeps_the_stock_a_member():
    exc = t("MID", "i:9", "EXCLUDED", D(2024, 9, 30), doc="aug")
    rv = Revocation("aug", "sep", "MID", "9", "EXCLUDED", D(2024, 9, 30))
    kept, cancelled, _ = apply_revocations([exc], [rv])
    assert kept == [] and cancelled == [(rv, exc)]
    w = walk_back({"MID": frozenset({"i:9"})}, kept, START, ANCHOR)
    assert not w.discrepancies and w.initial["MID"] == {"i:9"}


def test_a_revocation_that_matches_nothing_is_reported_never_dropped():
    inc = t("MID", "i:5", "INCLUDED", D(2024, 9, 30), doc="aug")
    wrong_date = Revocation("aug", "sep", "MID", "5", "INCLUDED", D(2024, 10, 1))
    wrong_kind = Revocation("aug", "sep", "MID", "5", "EXCLUDED", D(2024, 9, 30))
    wrong_doc = Revocation("other", "sep", "MID", "5", "INCLUDED", D(2024, 9, 30))
    wrong_comp = Revocation("aug", "sep", "N50", "5", "INCLUDED", D(2024, 9, 30))
    kept, cancelled, unmatched = apply_revocations(
        [inc], [wrong_date, wrong_kind, wrong_doc, wrong_comp]
    )
    assert kept == [inc] and cancelled == []
    assert unmatched == [wrong_date, wrong_kind, wrong_doc, wrong_comp]


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


def test_a_reviewed_equivalence_makes_two_keys_of_one_issuer_the_same_entity():
    eq = equivalence_map([{"from": ["s:NESTLEIND"], "to": "i:1589"}])
    assert eq == {"s:NESTLEIND": "i:1589"}
    trs = [
        t("N50", "s:NESTLEIND", "EXCLUDED", D(2022, 3, 31)),
        t("N50", "i:2", "INCLUDED", D(2022, 3, 31)),
    ]
    out = unify_entities(trs, eq)
    assert [x.entity for x in out] == ["i:1589", "i:2"] and out[0].action == "EXCLUDED"
    assert unify_entities(trs, {}) == trs  # no equivalence, nothing changes


def test_an_equivalence_must_be_unambiguous():
    with pytest.raises(ValueError, match="must be an instrument or a pre-listing symbol"):
        equivalence_map([{"from": ["s:A"], "to": "p:B"}])
    with pytest.raises(ValueError, match="maps to itself"):
        equivalence_map([{"from": ["i:1"], "to": "i:1"}])
    with pytest.raises(ValueError, match="mapped twice"):
        equivalence_map([{"from": ["s:A"], "to": "i:1"}, {"from": ["s:A"], "to": "i:2"}])
    with pytest.raises(ValueError, match="chain"):
        equivalence_map([{"from": ["s:A"], "to": "i:1"}, {"from": ["i:1"], "to": "i:2"}])


def test_an_isin_change_is_not_a_membership_disagreement_but_instruments_stay_separate():
    # Nifty 50 membership is continuous across the ISIN change: the old ISIN until 2024-01-04, the new from 5 Jan
    trs = [t("N50", "i:2", "EXCLUDED", D(2025, 1, 6)), t("N50", "i:3", "INCLUDED", D(2025, 1, 6))]
    w = walk_back({"N50": frozenset({"i:3"})}, trs, START, ANCHOR)
    snap = {
        D(2024, 6, 28): frozenset({"i:9", "i:1"})
    }  # the snapshot of that month names the OLD isin
    w2 = walk_back(
        {"N50": frozenset({"i:9", "i:2"})}, [], START, ANCHOR
    )  # reconstruction names the NEW one
    plain = reconcile(w2, ["N50"], snap)
    assert plain[0]["only_in_snapshot"] == ["i:1"] and plain[0]["only_in_reconstruction"] == ["i:2"]
    same = reconcile(w2, ["N50"], snap, same_issuer={"i:1": "i:2"})
    assert same[0]["only_in_snapshot"] == [] and same[0]["only_in_reconstruction"] == []
    assert same[0]["common"] == ["i:2", "i:9"]
    # the walk itself still holds the two instruments apart
    assert w.initial["N50"] == {"i:2"} and w2.initial["N50"] == {"i:9", "i:2"}


# ---- ISIN-change handover: one issuer, two instruments, never both members on one day ----
OLD, NEW, EFF = 2653, 1589, D(2024, 1, 5)
CONV = [(OLD, NEW, EFF)]


def hv(*ivs):
    return sorted(hand_over_isin_changes(list(ivs), CONV), key=lambda i: (i.start, i.entity))


def test_membership_running_across_the_change_is_split_on_the_effective_date():
    out = hv(Interval(f"i:{NEW}", START, None, "WINDOW_START_BACKWARD_WALK"))
    assert out == [
        Interval(f"i:{OLD}", START, EFF, "WINDOW_START_BACKWARD_WALK"),  # last member day 4 Jan
        Interval(f"i:{NEW}", EFF, None, "ISIN_CHANGE_HANDOVER"),  # first member day 5 Jan
    ]


def test_a_bounded_interval_keeps_its_end_on_the_new_instrument():
    out = hv(Interval(f"i:{NEW}", D(2022, 1, 1), D(2025, 6, 1), "EVENT"))
    assert out == [
        Interval(f"i:{OLD}", D(2022, 1, 1), EFF, "EVENT"),
        Interval(f"i:{NEW}", EFF, D(2025, 6, 1), "ISIN_CHANGE_HANDOVER"),
    ]


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (
            D(2022, 1, 1),
            D(2023, 6, 1),
            [f"i:{OLD}"],
        ),  # ended before the change: the old security only
        (D(2022, 1, 1), EFF, [f"i:{OLD}"]),  # exclusive end exactly on the change day
        (EFF, None, [f"i:{NEW}"]),  # starts exactly on the change day: nothing to split
        (D(2025, 1, 1), None, [f"i:{NEW}"]),  # after the change: unchanged
    ],
)
def test_intervals_not_spanning_the_change_go_whole_to_the_instrument_trading_then(
    start, end, expected
):
    out = hv(Interval(f"i:{NEW}", start, end, "EVENT"))
    assert [i.entity for i in out] == expected
    assert (out[0].start, out[0].end) == (start, end)
    assert out[0].start_basis == "EVENT"  # nothing was split: the basis is untouched


def test_an_old_instrument_interval_is_clipped_at_the_change_and_never_outlives_it():
    out = hv(Interval(f"i:{OLD}", D(2022, 1, 1), None, "EVENT"))
    assert out == [
        Interval(f"i:{OLD}", D(2022, 1, 1), EFF, "EVENT"),
        Interval(f"i:{NEW}", EFF, None, "ISIN_CHANGE_HANDOVER"),
    ]


def test_the_two_instruments_are_never_members_on_the_same_day():
    out = hv(Interval(f"i:{NEW}", START, None, "WINDOW_START_BACKWARD_WALK"))
    day = START
    while day < D(2024, 3, 1):
        held = [i.entity for i in out if i.start <= day and (i.end is None or day < i.end)]
        assert len(held) == 1, (day, held)  # exactly one: continuous issuer membership, never two
        assert held[0] == (f"i:{OLD}" if day < EFF else f"i:{NEW}")
        day += timedelta(days=1)


def test_other_entities_and_no_conversions_are_left_alone():
    other = Interval("i:9", START, None, "EVENT")
    sym = Interval("s:NESTLEIND", START, EFF, "EVENT")
    assert sorted(hv(other, sym), key=lambda i: i.entity) == [other, sym]
    assert hand_over_isin_changes([Interval(f"i:{NEW}", START, None, "EVENT")], []) == [
        Interval(f"i:{NEW}", START, None, "EVENT")
    ]


def test_blocked_spans_are_handed_over_the_same_way():
    spans = {
        f"i:{NEW}": [(D(2023, 12, 1), D(2024, 2, 1)), (D(2025, 1, 1), D(2025, 2, 1))],
        "i:9": [(START, EFF)],
    }
    out = hand_over_spans(spans, CONV)
    assert out == {
        f"i:{OLD}": [(D(2023, 12, 1), EFF)],
        f"i:{NEW}": [(EFF, D(2024, 2, 1)), (D(2025, 1, 1), D(2025, 2, 1))],
        "i:9": [(START, EFF)],
    }


def test_a_span_wholly_before_or_wholly_after_the_change_goes_to_one_instrument_only():
    assert hand_over_spans({f"i:{NEW}": [(D(2022, 1, 1), D(2022, 2, 1))]}, CONV) == {
        f"i:{OLD}": [(D(2022, 1, 1), D(2022, 2, 1))]
    }
    assert hand_over_spans({f"i:{OLD}": [(D(2025, 1, 1), D(2025, 2, 1))]}, CONV) == {
        f"i:{NEW}": [(D(2025, 1, 1), D(2025, 2, 1))]
    }


def _void_tr(doc, comp, sym, action, eff):
    return Transition(comp, f"s:{sym}", sym, action, eff, D(2020, 2, 18), doc, "s", "h", "v7", 1)


def test_a_release_declared_null_and_void_loses_only_the_changes_it_names_by_date():
    march27, march19 = D(2020, 3, 27), D(2020, 3, 19)
    trs = [
        _void_tr("pr_19032020", "N50", "AAA", "INCLUDED", march27),  # replacement that was voided
        _void_tr(
            "pr_19032020", "N50", "YESBANK", "EXCLUDED", march19
        ),  # the same release's change that STOOD (it took effect on 19 March)
        _void_tr("pr_12032020", "MID100", "BBB", "EXCLUDED", march27),  # another voided release
        _void_tr(
            "pr_10062020", "MID100", "BBB", "INCLUDED", D(2020, 6, 26)
        ),  # the review that replaced them
    ]
    voids = [
        Void("pr_19032020", march27, "pr_13052020"),
        Void("pr_12032020", march27, "pr_13052020"),
    ]
    kept, voided, unmatched = apply_voids(trs, voids)
    assert [(t.doc_id, t.symbol) for t in kept] == [
        ("pr_19032020", "YESBANK"),
        ("pr_10062020", "BBB"),
    ]
    assert sorted((v.doc_id, t.symbol) for v, t in voided) == [
        ("pr_12032020", "BBB"),
        ("pr_19032020", "AAA"),
    ]
    assert unmatched == []


def test_a_void_that_matches_nothing_is_reported_never_silently_dropped_and_nothing_is_invented():
    trs = [_void_tr("pr_a", "N50", "AAA", "INCLUDED", D(2020, 3, 27))]
    kept, voided, unmatched = apply_voids(trs, [Void("pr_zzz", D(2020, 3, 27), "pr_13052020")])
    assert kept == trs and voided == [] and [u.doc_id for u in unmatched] == ["pr_zzz"]
    assert apply_voids([], [])[0] == []
