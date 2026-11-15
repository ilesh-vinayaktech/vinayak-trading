# ruff: noqa: E501
"""Item E, scenarios 1 and 3 against the real reader: a split or bonus that takes effect after T changes no feature value for T; the instrument-scoped
history does not mix ISINs while the issuer-scoped one is continuous."""

from datetime import date
from decimal import Decimal as D

import pytest

from algo.data.reader import BarReader
from algo.data.store.migrate import migrate
from algo.features import registry, store
from tests.integration.features.test_store import sessions
from tests.support.bt import add_action, put_bars

pytestmark = pytest.mark.integration
JAN_END = date(2026, 1, 30)


def build(conn, with_action):
    from algo.data.store.instruments import InstrumentRepo

    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    iid = repo.add_instrument(x, "AAA")
    days = sessions()
    put_bars(conn, iid, {d: D(100 + (i * 7) % 23 + i % 3) for i, d in enumerate(days)})
    if with_action:
        add_action(
            conn, iid, date(2026, 3, 2), "split", num=D(10), den=D(1)
        )  # effective after every January day
    return iid


def january(conn, iid):
    bars = {iid: store.bars_from_reader(BarReader(conn, source="nse"), iid, date(2026, 3, 6))}
    out = {}
    for name, f in registry.DEFINITIONS.items():
        if f.needs_filings:
            continue  # a fundamental feature reads filings, never prices: a split cannot move it
        out[name] = {
            d: v
            for d, (v, _) in f.compute(sorted(bars[iid]), bars[iid]).items()
            if date(2026, 1, 1) <= d <= JAN_END
        }
    return out


def test_the_reader_really_does_rescale_the_adjusted_history_for_a_later_split(conn):
    """The premise of the test above: with the action on file the adjusted January closes are different, the raw ones are not."""
    iid = build(conn, with_action=True)
    bars = store.bars_from_reader(BarReader(conn, source="nse"), iid, date(2026, 3, 6))
    jan = [b for d, b in bars.items() if d.month == 1]
    assert all(b.close != b.raw_close and b.close == b.raw_close / 10 for b in jan)
    with_split = january(conn, iid)
    # a second world, same data, no action: values must be identical feature by feature
    conn.execute("DELETE FROM corporate_action")
    without = january(conn, iid)
    diff = {
        n: [d for d in with_split[n] if with_split[n][d] != without[n].get(d)] for n in with_split
    }
    assert {n: d for n, d in diff.items() if d} == {} and with_split == without
    assert all(
        with_split[n] for n in with_split if registry.DEFINITIONS[n].manifest["warmup_bars"] <= 21
    )  # the longer warm-ups have no January values here


def test_feature_inputs_are_instrument_scoped_so_two_isins_are_never_mixed(conn):
    """Scenario 3: the issuer-scoped series is the reader's own (tests/integration/test_issuer_reader.py); a feature reads one instrument's own history, so a
    symbol or ISIN change gives the new instrument a fresh warm-up rather than a stitched series."""
    iid = build(conn, with_action=False)
    reader = BarReader(conn, source="nse")
    called = []
    real = reader.load
    reader.load = lambda i, **k: called.append(("load", i)) or real(i, **k)  # type: ignore[method-assign]
    reader.issuer_load = lambda *a, **k: called.append(("issuer_load",))  # type: ignore[method-assign]
    store.bars_from_reader(reader, iid, date(2026, 3, 6))
    assert called == [("load", iid)]
