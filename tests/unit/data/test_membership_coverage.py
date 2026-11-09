from datetime import date

from algo.data.membership_coverage import (
    Event,
    MemberSpan,
    session_coverage,
    unusable_days,
)

D = date
S = [D(2025, 1, d) for d in (1, 2, 3, 6, 7)]  # sessions
CHECKED_UNTIL = D(2025, 1, 2)  # an independent official snapshot series covers sessions up to here


def cov(spans, events=(), bars=None, verified=False, sessions=S):
    has_bar = bars if bars is not None else (lambda iid, d: True)
    return {
        c.day: c
        for c in session_coverage(sessions, spans, list(events), has_bar, CHECKED_UNTIL, verified)
    }


def test_a_session_whose_members_are_all_tradable_known_and_verified_is_strict_eligible():
    c = cov(
        [MemberSpan("i:1", D(2024, 1, 1), None), MemberSpan("i:2", D(2024, 1, 1), None)],
        verified=True,
    )
    d = c[S[0]]
    assert (d.completeness, d.knowledge, d.independent_check, d.verification) == (
        "COMPLETE",
        "CONTEMPORANEOUS",
        "CHECKPOINTED",
        "VERIFIED",
    )
    assert d.strict_eligible and d.members == ("i:1", "i:2") and d.reasons == ()
    assert (
        c[S[3]].independent_check == "RELEASE_ONLY" and c[S[3]].strict_eligible
    )  # a check period is evidence quality, not a blocker


def test_provisional_evidence_is_never_strict_eligible_but_says_it_would_be():
    d = cov([MemberSpan("i:1", D(2024, 1, 1), None)])[S[0]]
    assert (
        not d.strict_eligible
        and d.eligible_once_verified
        and d.reasons == ("membership not person-verified",)
    )


def test_a_member_without_an_instrument_or_a_placeholder_makes_the_session_incomplete():
    c = cov([MemberSpan("i:1", D(2024, 1, 1), None), MemberSpan("s:GSPL", D(2024, 1, 1), S[2]),
             MemberSpan("p:DUMMYX", S[3], S[4])], verified=True)  # fmt: skip
    assert c[S[0]].completeness == "INCOMPLETE" and c[S[0]].untradable == ("s:GSPL",)
    assert c[S[2]].completeness == "COMPLETE"  # GSPL's span ends (exclusive) on S[2]
    assert c[S[3]].untradable == ("p:DUMMYX",) and not c[S[3]].strict_eligible
    assert c[S[4]].strict_eligible


def test_a_change_published_after_it_took_effect_is_retrospective_until_the_announcement():
    # listing replaces a placeholder effective S[1], but the only release stating it is dated S[3]
    spans = [MemberSpan("p:DUMMYX", D(2024, 1, 1), S[1]), MemberSpan("i:9", S[1], None)]
    ev = [Event("i:9", S[1], S[3]), Event("p:DUMMYX", S[1], S[3])]
    c = cov(spans, ev, verified=True)
    assert c[S[1]].knowledge == "RETROSPECTIVE" and c[S[1]].retrospective == ("i:9", "p:DUMMYX")
    assert c[S[2]].knowledge == "RETROSPECTIVE"  # still not published at the decision on S[2]
    assert (
        c[S[3]].knowledge == "CONTEMPORANEOUS" and c[S[3]].strict_eligible
    )  # release dated S[3] is known at its close
    assert (
        c[S[0]].knowledge == "CONTEMPORANEOUS" and c[S[0]].completeness == "INCOMPLETE"
    )  # placeholder member
    contemporaneous = cov(
        [MemberSpan("i:9", S[1], None)], [Event("i:9", S[1], S[0])], verified=True
    )
    assert contemporaneous[S[1]].knowledge == "CONTEMPORANEOUS"  # announced before it took effect


def test_a_tradable_member_without_a_bar_that_session_is_reported_and_blocks():
    c = cov([MemberSpan("i:1", D(2024, 1, 1), None), MemberSpan("i:2", D(2024, 1, 1), None)],
            bars=lambda iid, d: not (iid == 2 and d == S[2]), verified=True)  # fmt: skip
    assert c[S[2]].missing_bars == ("i:2",) and not c[S[2]].strict_eligible
    assert "member without a bar: i:2" in c[S[2]].reasons
    assert c[S[1]].missing_bars == () and c[S[1]].strict_eligible


def test_the_member_set_hash_is_stable_and_changes_with_the_set():
    a = cov([MemberSpan("i:1", D(2024, 1, 1), None), MemberSpan("i:2", D(2024, 1, 1), S[2])])
    b = cov(
        [MemberSpan("i:2", D(2024, 1, 1), S[2]), MemberSpan("i:1", D(2024, 1, 1), None)]
    )  # same, reordered
    assert a[S[0]].members_hash == b[S[0]].members_hash
    assert a[S[0]].members_hash != a[S[2]].members_hash  # i:2 left


def test_unusable_days_lists_every_session_a_strict_decision_must_skip_with_its_reasons():
    c = session_coverage(S, [MemberSpan("i:1", D(2024, 1, 1), None), MemberSpan("s:X", S[3], None)],
                         [], lambda iid, d: True, CHECKED_UNTIL, True)  # fmt: skip
    u = unusable_days(c)
    assert sorted(u) == [S[3], S[4]] and "member without an instrument: s:X" in u[S[3]]
