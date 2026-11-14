import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest
from hypothesis import given
from hypothesis import strategies as st

from algo.data.adjust.factors import ActionRecord
from algo.data.reader import Loaded
from algo.research.holdout_lock import (
    HoldoutAccess,
    Lock,
    LockMismatch,
    ResearchReader,
    from_file,
    research_minute_history,
)

LOCK = Lock(date(2024, 12, 31), date(2025, 1, 1), date(2026, 11, 13))


def row(day: date, close="100"):
    ts = datetime(day.year, day.month, day.day, 3, 45, tzinfo=UTC)
    c = D(close)
    return (ts, c, c, c, c, D(1000))


def action(day: date):
    return ActionRecord(day, "split", "ok", D(1), D(2), None, datetime(2020, 1, 1, tzinfo=UTC))


DAYS = [
    date(2024, 12, 27),
    date(2024, 12, 30),
    date(2024, 12, 31),
    date(2025, 1, 1),
    date(2025, 1, 2),
    date(2026, 3, 2),
]


class Inner:
    """A BarReader stand-in: the full data, holdout included, exactly as the unguarded reader would give it."""

    known_at = None
    visible_after = timedelta(0)
    source = "kite"
    cutoff = None
    conn = object()  # must not be reachable through the guard

    def _loaded(self, strict=False):
        rows = [row(d) for d in DAYS]
        recs = [action(date(2023, 5, 1)), action(date(2025, 6, 1))]
        through = list(DAYS)
        owners = [7] * len(rows)
        return Loaded(
            rows,
            recs,
            timedelta(0),
            strict,
            owners,
            through,
            frozenset({date(2024, 6, 1), date(2025, 7, 1)}),
        )

    def load(self, instrument_id, *, strict=False):
        return self._loaded(strict)

    def issuer_load(self, instrument_id, *, strict=False):
        return self._loaded(strict)

    def snapshot_hash(self, ids):
        return "h"

    def isin_links(self):
        return []


def reader():
    return ResearchReader(Inner(), LOCK)


def test_the_lock_hash_is_canonical_and_changes_with_every_field():
    a = Lock(date(2024, 12, 31), date(2025, 1, 1), date(2026, 11, 13))
    assert a.sha256 == Lock(date(2024, 12, 31), date(2025, 1, 1), date(2026, 11, 13)).sha256
    others = [
        Lock(date(2024, 12, 30), date(2025, 1, 1), date(2026, 11, 13)),
        Lock(date(2024, 12, 31), date(2025, 1, 2), date(2026, 11, 13)),
        Lock(date(2024, 12, 31), date(2025, 1, 1), date(2026, 11, 14)),
    ]
    assert len({a.sha256, *(o.sha256 for o in others)}) == 4


def test_a_lock_must_leave_development_before_the_holdout_and_the_holdout_non_empty():
    with pytest.raises(LockMismatch, match="before the holdout"):
        Lock(date(2025, 1, 1), date(2025, 1, 1), date(2026, 1, 1))
    with pytest.raises(LockMismatch, match="not before"):
        Lock(date(2024, 12, 31), date(2025, 1, 5), date(2025, 1, 4))


def test_the_file_is_read_strictly(tmp_path):
    good = {
        "development_end": "2024-12-31",
        "holdout_start": "2025-01-01",
        "holdout_end": "2026-11-13",
    }
    p = tmp_path / "lock.json"
    p.write_text(json.dumps(good))
    assert from_file(p) == LOCK
    for bad in (
        {**good, "extra": 1},
        {k: v for k, v in good.items() if k != "holdout_end"},
        {**good, "holdout_start": "soon"},
    ):
        p.write_text(json.dumps(bad))
        with pytest.raises(LockMismatch):
            from_file(p)
    with pytest.raises(LockMismatch, match="cannot read"):
        from_file(tmp_path / "missing.json")


def test_a_loaded_instrument_holds_no_bar_action_or_dividend_from_the_holdout():
    for loaded in (reader().load(7), reader().issuer_load(7), reader().load(7).lenient()):
        assert max(loaded.days) == date(2024, 12, 31)
        assert len(loaded.rows) == len(loaded.owners) == len(loaded.through) == 3
        assert [r.ex_date for r in loaded.recs] == [date(2023, 5, 1)]
        assert loaded.vendor_dividends == frozenset({date(2024, 6, 1)})


def test_asking_for_days_in_the_holdout_is_refused_not_silently_cut():
    r = reader()
    assert len(r.history(7, date(2024, 12, 1), date(2024, 12, 31)).bars) == 3
    assert len(r.issuer_history(7, date(2024, 12, 1), date(2024, 12, 31)).bars) == 3
    for end in (date(2025, 1, 1), date(2025, 1, 2), date(2030, 1, 1)):
        with pytest.raises(HoldoutAccess):
            r.history(7, date(2024, 12, 1), end)
        with pytest.raises(HoldoutAccess):
            r.issuer_history(7, date(2024, 12, 1), end)
        with pytest.raises(HoldoutAccess):
            r.load(7).history(date(2024, 12, 1), end)
        with pytest.raises(HoldoutAccess):
            r.load(7).lenient().history(date(2024, 12, 1), end)


def test_the_guard_exposes_only_what_research_needs():
    r = reader()
    assert (r.known_at, r.visible_after, r.source, r.cutoff) == (None, timedelta(0), "kite", None)
    assert r.snapshot_hash([7]) == "h" and r.isin_links() == []
    for name in ("conn", "_raw", "_kite_days", "inner", "lock_"):
        with pytest.raises(AttributeError):
            getattr(r, name)


def test_the_minute_history_is_refused_before_it_touches_the_database():
    with pytest.raises(HoldoutAccess):
        research_minute_history(None, LOCK, 7, date(2024, 12, 1), date(2025, 1, 1))


@given(
    end=st.dates(min_value=date(2024, 1, 1), max_value=date(2027, 12, 31)),
    asof_days=st.integers(0, 900),
)
def test_no_request_returns_a_bar_on_or_after_the_holdout_start(end, asof_days):
    r = reader()
    as_of = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=asof_days)
    try:
        h = r.history(7, date(2024, 1, 1), end, as_of=as_of)
    except HoldoutAccess:
        assert end >= LOCK.holdout_start
        return
    assert end < LOCK.holdout_start
    assert all(b.ts.date() < LOCK.holdout_start for b in h.bars)


def test_the_snapshot_hash_is_remembered_per_set_of_instruments():
    calls = []

    class Counting(Inner):
        def snapshot_hash(self, ids):
            calls.append(tuple(ids))
            return "h" + str(len(calls))

    r = ResearchReader(Counting(), LOCK)
    assert (
        r.snapshot_hash([3, 1, 2]) == r.snapshot_hash([2, 3, 1, 1]) == "h1"
    )  # order and repeats do not matter
    assert r.snapshot_hash([4]) == "h2" and calls == [(1, 2, 3), (4,)]
