# ruff: noqa: E501
"""Item E of docs/vti-phase1-spec.md: the look-ahead harness over the WHOLE registry. A feature added to the registry is covered here without
anyone remembering to; a feature deliberately written with a look-ahead is shown to fail it."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from algo.data import ratios as fr
from algo.features import registry
from algo.features._shared import SessionBar, q
from algo.features.fundamental import FilingsHistory

NAMES = sorted(registry.DEFINITIONS)


def make_days(n=330):
    out, d = [], date(2024, 1, 1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


DAYS = make_days()


def at(day):
    return datetime(day.year, day.month, day.day, 13, tzinfo=UTC)


def world(scale=D(1), skip=()):
    """Closes that wander (not monotonic, so every feature has structure to disagree about). `scale` multiplies the ADJUSTED series only: what a split
    that takes effect after the last day does to a reader that adjusts with everything it knows. Raw close and volume are what was traded."""
    bars = {}
    for i, d in enumerate(DAYS):
        if d in skip:
            continue
        c = D(100) + D(i % 17) * D("1.3") + D(i % 5) - D(i) * D("0.05")
        bars[d] = SessionBar(
            d, (c + D("1.5")) * scale, (c - D("1.2")) * scale, c * scale, c, D(10_000 + 37 * (i % 11)), at(d)
        )  # fmt: skip
    return bars


def quarters():
    """Quarterly filings of one company, each filed 45 days after its quarter ended, revenue and profit growing: some are filed inside the test window, some after it."""
    ends = [
        date(y, m, d)
        for y in (2022, 2023, 2024, 2025)
        for m, d in ((3, 31), (6, 30), (9, 30), (12, 31))
    ][3:-2]  # Dec 2022 .. Jun 2025
    out = []
    for k, end in enumerate(ends):
        filed_at = datetime.combine(
            end + timedelta(days=45), datetime.min.time(), tzinfo=UTC
        ) + timedelta(hours=11)
        figures = {
            "RevenueFromOperations": D(100 + 7 * k), "ProfitLossForPeriod": D(10 + k), "Expenses": D(80 + 5 * k), "ProfitBeforeTax": D(14 + k),
            "FinanceCosts": D(2), "DepreciationDepletionAndAmortisationExpense": D(3),
        }  # fmt: skip
        sheet = {
            "Equity": D(500 + 10 * k), "Assets": D(900 + 10 * k), "BorrowingsNoncurrent": D(100), "BorrowingsCurrent": D(50), "CurrentAssets": D(300), "CurrentLiabilities": D(200),
            "Inventories": D(40), "TradeReceivablesCurrent": D(60), "CashAndCashEquivalents": D(30),
        }  # fmt: skip
        year = {
            "CashFlowsFromUsedInOperatingActivities": D(30 + k),
            "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities": D(10),
            "ProfitLossForPeriod": D(10 + k),
            "RevenueFromOperations": D(100 + 7 * k),
        }
        out.append(fr.Quarter(end, filed_at, False, figures, year, sheet))
    return out


FILINGS = FilingsHistory({"CONSOLIDATED": quarters()})


def calc(name):
    """A registered feature as the harness runs it: price features from the bars, fundamental ones from the bars and this company's filings (cut at `cut` when given)."""
    d = registry.DEFINITIONS[name]

    def f(sessions, bars, cut=None):
        return d.calc(sessions, bars, FILINGS if cut is None else FILINGS.truncated(cut))

    return f


def violations(compute, cut_index):
    """Days at or before the cut whose value differs between the full history and the history truncated at the cut."""
    full = compute(DAYS, world())
    cut = DAYS[cut_index]
    short = compute(DAYS[: cut_index + 1], {d: b for d, b in world().items() if d <= cut}, cut)
    return [d for d in DAYS[: cut_index + 1] if full.get(d) != short.get(d)]


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("cut", [60, 150, 299])
def test_truncating_the_data_at_T_changes_no_value_for_T_or_earlier(name, cut):
    assert violations(calc(name), cut) == []


@pytest.mark.parametrize("name", NAMES)
def test_a_split_taking_effect_after_T_does_not_change_the_value_for_T(name):
    """Scenario 1. A later split halves every adjusted price on file (the bar for T included); the value for T must not know about it."""
    f = calc(name)
    before, after = f(DAYS, world()), f(DAYS, world(scale=D("0.5")))
    assert before and set(before) == set(after)
    assert {d: v for d, (v, _) in before.items()} == {d: v for d, (v, _) in after.items()}


@pytest.mark.parametrize("name", NAMES)
def test_a_missing_session_gives_an_absent_value_and_does_not_shift_the_window(name):
    """Scenario 4. Remove one session of the instrument (the session itself stays a session: other instruments traded). Every day whose window contains it
    has no value; every other day's value is the one it had with the bar present."""
    f = calc(name)
    hole = DAYS[200]
    full, holey = f(DAYS, world()), f(DAYS, world(skip={hole}))
    assert hole not in holey
    manifest = registry.DEFINITIONS[name].manifest
    warm = manifest["warmup_bars"]
    recursive = manifest["family"] in ("price", "technical") and manifest["formula"] in (
        "atr",
        "atr_pct",
        "rsi",
    )  # a gap restarts Wilder's chain, so later values differ
    for i, d in enumerate(DAYS):
        if d == hole or i < warm:
            continue
        if i - warm < 200 <= i or (
            recursive and 200 < i < 200 + warm
        ):  # the hole is inside the window (or the chain is still restarting)
            assert d not in holey, (name, d)
        elif recursive and i > 200:
            assert d in holey  # the chain is back, its values depend on where it restarted
        else:
            assert holey.get(d) == full.get(d), (name, d)


@pytest.mark.parametrize("name", NAMES)
def test_a_halted_instrument_with_no_bars_gives_no_value(name):
    assert calc(name)(DAYS, {}) == {}


def leaky(sessions, bars, cut=None):
    """A feature written with a look-ahead: tomorrow's close over today's."""
    out = {}
    for i, d in enumerate(sessions[:-1]):
        if d in bars and sessions[i + 1] in bars:
            out[d] = (
                q(bars[sessions[i + 1]].close / bars[d].close - 1),
                bars[sessions[i + 1]].available_at,
            )
    return out


def test_a_feature_with_a_deliberate_look_ahead_fails_the_harness():
    assert violations(leaky, 150) == [DAYS[150]]  # the value for T itself used T+1


def test_the_harness_covers_every_registered_feature():
    assert len(NAMES) == 35 and set(NAMES) == set(registry.DEFINITIONS)


@pytest.mark.parametrize("name", NAMES)
def test_computing_every_month_in_one_pass_gives_exactly_the_rows_of_computing_each_month_alone(
    name,
):
    """The single pass the job and the validation use is only a speed-up: for every feature, including the recursive ones and the fundamental ones, each month's rows
    (and their digest) are the ones the one-month-at-a-time path gives."""
    from algo.features import store

    bars = {1: world(), 2: world(D("0.5"))}
    filings = {1: FILINGS, 2: FILINGS}
    months = sorted({d.replace(day=1) for d in DAYS})
    by_month = store.compute_rows_by_month(name, months, bars, filings)
    assert sorted(by_month) == months
    for m in months:
        alone = store.compute_rows(name, m, bars, filings)
        assert by_month[m] == alone and store.rows_sha256(by_month[m]) == store.rows_sha256(
            alone
        ), (name, m)
    only_some = store.compute_rows_by_month(name, months[3:5], bars, filings)
    assert sorted(only_some) == months[3:5] and only_some[months[3]] == by_month[months[3]]
