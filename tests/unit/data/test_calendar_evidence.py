from datetime import date
from decimal import Decimal as D

from algo.data import calendar_evidence as ce
from algo.data.providers.nse_bhavcopy_legacy import LegacyBhav


def bhav(day, closes, prevs, n=None):
    keys = [(f"S{i}", "EQ") for i in range(len(closes))]
    return LegacyBhav(frozenset({day}), len(closes), dict(zip(keys, map(D, closes), strict=True)),
                      dict(zip(keys, map(D, prevs), strict=True)))  # fmt: skip


MON, TUE, WED, THU, FRI = (date(2024, 1, d) for d in (1, 2, 3, 4, 5))
N = ce.MIN_SYMBOLS
CL = [str(100 + i) for i in range(N)]


def test_a_dated_file_proves_trading_and_a_misdated_one_is_flagged():
    odd = LegacyBhav(frozenset({MON}), 1, {}, {})
    r = ce.classify([MON, TUE], {MON: bhav(MON, CL, CL), TUE: odd}, set())
    assert r[MON].status == ce.TRADED and r[TUE].status == ce.MISMATCH


def test_a_missing_file_between_chained_sessions_is_an_inferred_closure():
    files = {MON: bhav(MON, CL, CL), THU: bhav(THU, CL, CL)}  # THU prev == MON close
    r = ce.classify([TUE, WED], files, {TUE, WED})
    assert r[TUE] == r[WED] == ce.Record(ce.CLOSED, MON, THU, N, N)


def test_a_missing_file_between_sessions_that_do_not_chain_is_an_archive_gap():
    later_prev = [str(200 + i) for i in range(N)]  # a session in between moved every close
    files = {MON: bhav(MON, CL, CL), THU: bhav(THU, CL, later_prev)}
    r = ce.classify([TUE], files, {TUE})
    assert r[TUE].status == ce.GAP and (r[TUE].symbols_in_both, r[TUE].symbols_equal) == (N, 0)


def test_the_chain_threshold_is_inclusive_and_needs_enough_symbols():
    k = N - 1  # 19 of 20 = 0.95: still a chain
    prev_ok = CL[:k] + ["999"]
    ok = ce.classify([TUE], {MON: bhav(MON, CL, CL), THU: bhav(THU, CL, prev_ok)}, {TUE})
    assert ok[TUE].status == ce.CLOSED and ok[TUE].symbols_equal == k
    worse = CL[: k - 1] + ["999", "998"]
    bad = ce.classify([TUE], {MON: bhav(MON, CL, CL), THU: bhav(THU, CL, worse)}, {TUE})
    assert bad[TUE].status == ce.GAP
    few = CL[: N - 1]
    tiny = ce.classify([TUE], {MON: bhav(MON, few, few), THU: bhav(THU, few, few)}, {TUE})
    assert tiny[TUE].status == ce.GAP  # too few symbols to infer anything


def test_unfetched_dates_and_dates_without_a_confirmed_session_on_each_side_stay_unexamined():
    files = {MON: bhav(MON, CL, CL), FRI: bhav(FRI, CL, CL)}
    r = ce.classify(
        [TUE, THU, date(2023, 12, 29), date(2024, 1, 8)],
        files,
        {THU, date(2023, 12, 29), date(2024, 1, 8)},
    )
    assert r[TUE].status == ce.UNEXAMINED  # never fetched
    assert r[THU].status == ce.CLOSED
    assert r[date(2023, 12, 29)].status == ce.UNEXAMINED  # nothing earlier
    assert r[date(2024, 1, 8)].status == ce.UNEXAMINED  # nothing later


def test_a_misdated_file_is_not_used_as_a_confirmed_neighbour():
    odd = LegacyBhav(
        frozenset({WED}), N, dict.fromkeys([(f"S{i}", "EQ") for i in range(N)], D(1)), {}
    )
    files = {MON: bhav(MON, CL, CL), TUE: odd, FRI: bhav(FRI, CL, CL)}
    r = ce.classify([THU], files, {THU})
    assert (r[THU].earlier, r[THU].later) == (MON, FRI)


def test_file_findings_report_duplicates_short_files_misdated_files_and_chain_breaks():
    short = LegacyBhav(frozenset({MON}), 5, {}, {}, duplicates=0)
    dup = LegacyBhav(frozenset({TUE}), N + 500, dict.fromkeys([(f"S{i}", "EQ") for i in range(N)], D(1)),
                     dict.fromkeys([(f"S{i}", "EQ") for i in range(N)], D(1)), duplicates=3)  # fmt: skip
    odd = LegacyBhav(frozenset({WED}), 500, {}, {})
    files = {MON: short, TUE: dup, THU: odd}
    recs = ce.classify([MON, TUE, WED, THU], files, {WED})
    found, _ = ce.file_findings(files, recs)
    kinds = {(f.kind, f.day) for f in found}
    assert kinds == {  # MON has no symbols, so MON->TUE cannot chain either
        (ce.SHORT_FILE, MON),
        (ce.DUPLICATE_ROWS, TUE),
        (ce.MISMATCH, THU),
        (ce.CHAIN_BREAK, TUE),
    }


def test_consecutive_confirmed_sessions_are_chained_and_a_weak_chain_is_a_finding():
    ok = {MON: bhav(MON, CL, CL, 500), TUE: bhav(TUE, CL, CL, 500)}
    ok = {d: LegacyBhav(f.days, 500, f.close, f.prev_close) for d, f in ok.items()}
    recs = ce.classify([MON, TUE], ok, set())
    found, links = ce.file_findings(ok, recs)
    assert found == [] and links == {TUE: (MON, N, N)}
    moved = [str(200 + i) for i in range(N)]
    bad = {
        MON: ok[MON],
        TUE: LegacyBhav(
            frozenset({TUE}),
            500,
            ok[TUE].close,
            dict(zip(ok[TUE].close, map(D, moved), strict=True)),
        ),
    }
    f2, _ = ce.file_findings(bad, ce.classify([MON, TUE], bad, set()))
    assert [(f.kind, f.day) for f in f2] == [(ce.CHAIN_BREAK, TUE)]
    few = {
        d: LegacyBhav(
            f.days,
            500,
            {k: v for k, v in list(f.close.items())[:5]},
            {k: v for k, v in list(f.prev_close.items())[:5]},
        )
        for d, f in ok.items()
    }
    f3, _ = ce.file_findings(few, ce.classify([MON, TUE], few, set()))
    assert [f.kind for f in f3] == [ce.CHAIN_BREAK]  # too few common symbols to call it a chain


def test_sessions_with_an_unexamined_or_gap_weekday_between_them_are_not_chained():
    files = {MON: bhav(MON, CL, CL), THU: bhav(THU, CL, CL)}
    files = {d: LegacyBhav(f.days, 500, f.close, f.prev_close) for d, f in files.items()}
    unexamined = ce.classify([MON, TUE, THU], files, set())
    assert ce.file_findings(files, unexamined) == ([], {})
    closed = ce.classify([MON, TUE, THU], files, {TUE})
    assert ce.file_findings(files, closed)[1] == {THU: (MON, N, N)}


def test_a_weekend_session_between_two_weekday_sessions_splits_the_chain():
    sat = date(2024, 1, 6)
    fri_prev = date(2024, 1, 5)
    a, b, c = (bhav(d, CL, CL) for d in (fri_prev, sat, MON))
    files = {
        d: LegacyBhav(f.days, 500, f.close, f.prev_close)
        for d, f in ((fri_prev, a), (sat, b), (date(2024, 1, 8), c))
    }
    files[date(2024, 1, 8)] = LegacyBhav(frozenset({date(2024, 1, 8)}), 500, c.close, c.prev_close)
    recs = ce.classify([fri_prev, date(2024, 1, 8)], files, set())
    found, links = ce.file_findings(files, recs)
    assert found == [] and set(links) == {
        sat,
        date(2024, 1, 8),
    }  # Fri->Sat and Sat->Mon, not Fri->Mon
