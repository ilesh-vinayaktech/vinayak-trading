from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal as D

from algo.data.adjust.factors import ActionRecord
from algo.data.kite_compare import compare
from algo.data.reader import Loaded

TODAY = date(2026, 11, 11)
KNOWN = datetime(2000, 1, 1, tzinfo=UTC)
N = 120


def days(n, end=TODAY):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


DAYS = days(N)


def rows(closes):
    return [(datetime.combine(d, time(3, 45), UTC), c, c, c, c, D(1000)) for d, c in closes]


def loaded(closes, recs=(), through=None):
    return Loaded(rows(closes), list(recs), timedelta(0), False, None, through)


def kite_of(closes):
    """Kite's side: adjusted by the vendor through today, so nothing is left for us to apply."""
    return loaded(closes, through=[TODAY] * len(closes))


def split(ex, status="ok"):
    return ActionRecord(ex, "split", status, D(2), D(1), None, KNOWN)


def series():
    return [(d, D(100) + i) for i, d in enumerate(DAYS)]


def scaled(closes, factor, where):
    return [(d, c * factor if where(i, d) else c) for i, (d, c) in enumerate(closes)]


def test_two_sources_that_agree_after_the_recorded_split_are_a_match():
    ex = DAYS[60]
    raw = scaled(
        series(), D(2), lambda i, d: d < ex
    )  # raw bhavcopy: pre-split prices are twice the adjusted ones
    r = compare(kite_of(series()), loaded(raw, [split(ex)]))
    assert (r.status, r.days, r.outliers, r.max_deviation) == ("MATCH", N, 0, 0)


def test_a_few_stray_days_do_not_spoil_a_match_but_are_counted():
    kite = scaled(series(), D("1.02"), lambda i, d: i in (10, 50))
    r = compare(kite_of(kite), loaded(series()))
    assert (r.status, r.outliers) == ("MATCH", 2) and r.max_deviation == D("0.02")


def test_kite_not_adjusting_a_split_we_recorded_is_a_step_explained_by_that_action():
    ex = DAYS[60]
    nse = loaded(scaled(series(), D(2), lambda i, d: d < ex), [split(ex)])
    kite = kite_of(
        scaled(series(), D(2), lambda i, d: d < ex)
    )  # Kite claims to be adjusted but left the old prices raw
    r = compare(kite, nse)
    assert (r.status, r.step_date, r.step_ratio) == ("STEP", ex, D(2))
    assert r.explained_by == ("split", ex, "ok")


def test_kite_adjusting_something_we_have_no_record_of_is_a_step_with_no_explanation():
    ex = DAYS[40]
    nse = loaded(scaled(series(), D(2), lambda i, d: d < ex))  # raw, and we hold no action for it
    r = compare(kite_of(series()), nse)
    assert (r.status, r.step_date, r.step_ratio, r.explained_by) == ("STEP", ex, D("0.5"), None)


def test_an_action_still_under_review_is_named_when_it_sits_at_the_step():
    ex = DAYS[40]
    nse = loaded(scaled(series(), D(2), lambda i, d: d < ex), [split(ex, status="review")])
    r = compare(kite_of(series()), nse)
    assert r.status == "STEP" and r.explained_by == ("split", ex, "review")


def test_a_difference_at_the_recent_end_is_a_step_too():
    cut = DAYS[100]
    nse = loaded(scaled(series(), D("1.05"), lambda i, d: d >= cut))
    r = compare(kite_of(series()), nse)
    assert (r.status, r.step_date) == ("STEP", cut) and r.step_ratio == D(1) / D("1.05")


def test_the_same_small_difference_on_every_day_is_a_constant_offset_not_a_step():
    nse = loaded([(d, c * D("1.03")) for d, c in series()])
    r = compare(kite_of(series()), nse)
    assert (r.status, r.step_date) == ("OFFSET", None) and r.step_ratio == D(1) / D("1.03")
    assert (
        compare(kite_of(series()), nse, tolerance=D("0.05")).status == "MATCH"
    )  # inside a looser tolerance


def test_scattered_disagreement_is_reported_as_diverging():
    nse = loaded(
        [
            (d, c * (D("1.2") if i % 3 == 0 else D("0.8") if i % 3 == 1 else D(1)))
            for i, (d, c) in enumerate(series())
        ]
    )
    r = compare(kite_of(series()), nse)
    assert r.status == "DIVERGES" and r.step_date is None and r.max_deviation >= D("0.2")


def test_a_step_whose_size_wanders_is_not_called_a_step():
    ex = DAYS[60]
    wandering = [
        (d, c * (D(1) + D(i % 5) / D(10)) if d < ex else c) for i, (d, c) in enumerate(series())
    ]
    assert compare(kite_of(series()), loaded(wandering)).status == "DIVERGES"


def test_too_little_in_common_is_said_not_judged():
    short = kite_of(series()[:10])
    assert compare(short, loaded(series())).status == "NO_OVERLAP"
    assert compare(loaded([]), loaded([])).status == "NO_OVERLAP"


def test_a_bump_in_the_middle_that_goes_away_again_is_not_a_step():
    nse = loaded(scaled(series(), D("1.1"), lambda i, d: 40 <= i < 60))
    r = compare(kite_of(series()), nse)
    assert (r.status, r.step_date) == ("DIVERGES", None) and r.outliers == 20


def test_which_comparisons_are_breaches_and_which_are_not():
    from algo.data.kite_compare import Comparison, breaches

    ok = Comparison("MATCH", 100, 0, D("0.001"))
    none = Comparison("NO_OVERLAP", 5, 0, D(0))
    explained = Comparison(
        "STEP", 100, 50, D("0.1"), DAYS[10], D("0.9"), ("dividend", DAYS[10], "ok")
    )
    unexplained = Comparison("STEP", 100, 50, D("0.1"), DAYS[10], D("0.9"), None)
    diverges, offset = (
        Comparison("DIVERGES", 100, 90, D("0.3")),
        Comparison("OFFSET", 100, 100, D("0.1")),
    )
    got = breaches(
        {"A": ok, "B": none, "C": explained, "D": unexplained, "E": diverges, "F": offset}
    )
    assert sorted(got) == [
        "D",
        "E",
        "F",
    ]  # a step we can explain by a recorded action, a match and too little overlap are not breaches
    assert got["E"] == "DIVERGES: scattered differences, largest 0.300"
    assert got["D"].startswith("STEP: no recorded action near")


def tiny():
    """A price cut by big splits and bonuses (RAMASTEEL's old prices): about half a rupee."""
    return [
        (d, D(c))
        for d, c in zip(DAYS, [D("0.52"), D("0.53"), D("0.57"), D("0.58")] * (N // 4), strict=True)
    ]


def to_tick(closes):
    """Kite quotes prices in 0.05 steps, so a heavily adjusted old price is rounded to the nearest 0.05."""
    return [(d, (c / D("0.05")).quantize(D(1)) * D("0.05")) for d, c in closes]


def test_kites_tick_rounding_on_a_tiny_adjusted_price_is_not_a_disagreement():
    r = compare(kite_of(to_tick(tiny())), loaded(tiny()))
    assert (r.status, r.outliers) == ("MATCH", 0)
    assert r.max_deviation > D(
        "0.03"
    )  # still reported: a 4% difference on paper, one rounding step in fact


def test_a_whole_tick_of_difference_on_a_tiny_price_is_still_caught():
    kite = [(d, c + D("0.05")) for d, c in tiny()]  # one full tick away on every day, not rounding
    assert compare(kite_of(kite), loaded(tiny())).status == "OFFSET"


def test_a_real_step_on_a_tiny_price_is_still_a_step():
    ex = DAYS[60]
    kite = to_tick(
        scaled(tiny(), D(2), lambda i, d: d < ex)
    )  # Kite adjusted something we did not, then rounded to its tick
    r = compare(kite_of(kite), loaded(tiny()))
    assert (r.status, r.step_date) == ("STEP", ex)
