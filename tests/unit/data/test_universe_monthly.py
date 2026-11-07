from datetime import date

from algo.data.universe_monthly import (
    Diff,
    Ev,
    Snap,
    count_checks,
    gap_checks,
    reconcile,
    series,
    transitions,
    union_checks,
)  # fmt: skip

D = date
M1, M2, M3 = D(2020, 1, 31), D(2020, 2, 28), D(2020, 3, 31)


def snap(comp, d, *syms):
    return Snap(comp, d, {f"i:{s}": f"S{s}" for s in syms})


def ev(sym, action, eff, comp="NIFTY_50", doc="d"):
    return Ev(f"i:{sym}", f"S{sym}", comp, action, eff, doc)


def kinds(diffs):
    return sorted((d.kind, d.key, d.end) for d in diffs)


def test_free_float_and_plain_midcap_100_are_one_series_and_full_is_another():
    assert series("MIDCAP_100_FREE_FLOAT") == series("MIDCAP_100") == "MIDCAP_100"
    assert series("MIDCAP_100_FULL") == "MIDCAP_100_FULL" and series("NIFTY_50") == "NIFTY_50"


def test_events_that_explain_the_next_snapshot_leave_nothing_to_report():
    snaps = [snap("NIFTY_50", M1, 1, 2), snap("NIFTY_50", M2, 1, 3)]
    events = [ev(2, "EXCLUDED", D(2020, 2, 10)), ev(3, "INCLUDED", D(2020, 2, 10))]
    assert transitions("NIFTY_50", snaps, events) == []


def test_an_event_on_the_report_date_is_inside_its_window_and_one_on_the_previous_date_is_not():
    snaps = [snap("NIFTY_50", M1, 1), snap("NIFTY_50", M2, 1, 2)]
    assert transitions("NIFTY_50", snaps, [ev(2, "INCLUDED", M2)]) == []  # effective on the date
    out = transitions("NIFTY_50", snaps, [ev(2, "INCLUDED", M1)])  # already in the first snapshot
    assert kinds(out) == [("UNEXPLAINED_ADD", "i:2", M2)]


def test_changes_nothing_explains_are_reported_with_nearby_events_as_context():
    snaps = [snap("NIFTY_50", M1, 1, 2), snap("NIFTY_50", M2, 1, 3)]
    far = ev(3, "INCLUDED", D(2020, 3, 20), doc="later")  # outside the window but near
    out = transitions("NIFTY_50", snaps, [far])
    assert kinds(out) == [("UNEXPLAINED_ADD", "i:3", M2), ("UNEXPLAINED_REMOVE", "i:2", M2)]
    add = next(d for d in out if d.kind == "UNEXPLAINED_ADD")
    assert (
        add.symbol == "S3"
        and add.start == M1
        and add.context == ("2020-03-20 NIFTY_50 INCLUDED (later)",)
    )
    assert "no event adds it" in add.detail
    assert next(d for d in out if d.kind == "UNEXPLAINED_REMOVE").detail == (
        "was a member, no event removes it, yet it is gone"
    )


def test_an_event_whose_effect_is_not_in_the_snapshot_is_a_different_finding():
    snaps = [snap("NIFTY_50", M1, 1, 2), snap("NIFTY_50", M2, 1, 2)]
    out = transitions(
        "NIFTY_50", snaps, [ev(2, "EXCLUDED", D(2020, 2, 3)), ev(5, "INCLUDED", D(2020, 2, 3))]
    )
    assert kinds(out) == [("EVENT_NOT_OBSERVED", "i:2", M2), ("EVENT_NOT_OBSERVED", "i:5", M2)]
    assert {d.detail for d in out} == {
        "a removal event is in the window, yet it is still a member",
        "an inclusion event is in the window, yet it is not a member",
    }


def test_snapshots_more_than_a_month_apart_say_so_and_voided_or_other_index_events_are_ignored():
    snaps = [snap("NIFTY_50", M1, 1), snap("NIFTY_50", M3, 1, 2)]  # February missing
    out = transitions("NIFTY_50", snaps, [ev(9, "INCLUDED", M2, comp="NIFTY_NEXT_50")])
    assert out[0].detail.endswith("(snapshots >45 days apart)") and out[0].key == "i:2"
    assert (
        transitions("NIFTY_50", [snap("NIFTY_50", M1, 1)], []) == []
    )  # one snapshot: no transition


def test_the_midcap_series_continues_across_its_rename():
    snaps = [
        snap("MIDCAP_100_FREE_FLOAT", D(2018, 3, 31), 1),
        snap("MIDCAP_100", D(2018, 4, 30), 1, 2),
    ]
    events = [ev(2, "INCLUDED", D(2018, 4, 10), comp="MIDCAP_100_FREE_FLOAT")]
    assert transitions("MIDCAP_100", snaps, events) == []


def test_nifty_200_is_compared_with_the_union_of_its_components():
    snaps = [snap("NIFTY_50", M1, 1), snap("NIFTY_NEXT_50", M1, 2), snap("MIDCAP_100", M1, 3),
             snap("NIFTY_200", M1, 1, 2, 3, 9)]  # fmt: skip
    out = union_checks(snaps)
    assert [(d.kind, d.key, d.symbol) for d in out] == [("UNION_MISMATCH", "i:9", "S9")]
    assert "none of its three components" in out[0].detail
    short = union_checks(snaps[:3] + [snap("NIFTY_200", M1, 1, 2)])
    assert [(d.key, d.detail) for d in short] == [
        ("i:3", "in the Nifty 50 / Next 50 / Midcap 100 snapshots but not in Nifty 200")
    ]
    assert union_checks(snaps[:3]) == [] and union_checks([snap("NIFTY_200", M1, 1)]) == []
    old = D(2017, 9, 29)
    legacy = union_checks([snap("NIFTY_50", old, 1), snap("NIFTY_NEXT_50", old, 2),
                           snap("MIDCAP_100_FULL", old, 3), snap("MIDCAP_100_FREE_FLOAT", old, 7),
                           snap("NIFTY_200", old, 1, 2, 3)])  # fmt: skip
    assert legacy == []  # before 2018-04 the FULL Midcap 100 is the third component, not free-float
    after = D(2018, 4, 30)
    assert union_checks([snap("NIFTY_50", after, 1), snap("NIFTY_NEXT_50", after, 2),
                         snap("MIDCAP_100_FULL", after, 7), snap("NIFTY_200", after, 1, 2)]) == []  # fmt: skip


def test_a_second_share_class_is_named_in_the_count_finding_not_hidden():
    s = Snap("NIFTY_50", M1, {f"i:{i}": f"S{i}" for i in range(50)} | {"i:99": "TATAMTRDVR"})
    out = count_checks([s])
    assert len(out) == 1 and out[0].detail == (
        "51 constituents, expected [50]; includes a second share class: TATAMTRDVR"
    )


def test_usual_sizes_are_expected_but_only_for_the_indices_we_know():
    assert count_checks([snap("NIFTY_50", M1, *range(50)), snap("NIFTY_200", M1, *range(201))]) == [
        Diff("COUNT_ANOMALY", "NIFTY_200", None, M1, "", "", "201 constituents, expected [200]")
    ]
    assert (
        count_checks([snap("NIFTY_50", M1, *range(49))])[0].detail
        == "49 constituents, expected [50]"
    )
    assert count_checks([snap("NIFTY_BANK", M1, 1)]) == []  # no expectation for other indices


def test_missing_months_are_listed():
    snaps = [snap("NIFTY_50", M1, 1), snap("NIFTY_50", M3, 1)]
    got = gap_checks("NIFTY_50", snaps, D(2020, 1, 1), D(2020, 4, 30))
    assert [(d.kind, d.end) for d in got] == [("GAP", D(2020, 2, 1)), ("GAP", D(2020, 4, 1))]
    assert gap_checks("NIFTY_50", snaps, D(2019, 12, 1), D(2019, 12, 31))[0].end == D(2019, 12, 1)


def test_reconcile_runs_every_check():
    snaps = [snap("NIFTY_50", M1, *range(1, 51)), snap("NIFTY_50", M2, *range(2, 52))]
    out = reconcile(snaps, [])
    assert {d.kind for d in out} == {"UNEXPLAINED_ADD", "UNEXPLAINED_REMOVE"}
    assert reconcile([snap("NIFTY_50", M1, 1)], []) == [
        Diff("COUNT_ANOMALY", "NIFTY_50", None, M1, "", "", "1 constituents, expected [50]")
    ]
