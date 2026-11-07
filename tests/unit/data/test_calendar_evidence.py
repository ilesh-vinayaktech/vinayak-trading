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
