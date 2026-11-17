from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from algo.data import nse_intel as n
from tests.support.bt import make_env
from tests.support.portal import open_app

NOW = datetime(2026, 11, 17, 13, 0, tzinfo=UTC)
DAY = date(2026, 11, 16)


@pytest.fixture(autouse=True)
def _open_research_lock_file(tmp_path, monkeypatch):
    """Integration tests read the research lock from a file with an open window far in the future (see tests/support/research_lock.py);
    a test that needs the lock in the database anchors it, a test of the lock itself patches the file again."""
    from algo.research import holdout_lock
    from tests.support.research_lock import write_lock_file

    monkeypatch.setattr(
        holdout_lock, "LOCK_FILE", write_lock_file(tmp_path / "research_holdout.json")
    )


def bar(conn, iid, day, close, volume, deliv):
    conn.execute(
        "INSERT INTO bar_1d (instrument_id, ts, open, high, low, close, volume, series, delivery_qty, source, dataset_version, ingested_at)"
        " VALUES (%s, %s::date + time '03:45', %s, %s, %s, %s, %s, 'EQ', %s, 'nse', 1, now())",
        (iid, day, close, close, close, close, volume, deliv),
    )


def sh(rid, sym, period, promoter, fii=None, dii=None, mf=None, when=NOW):
    return (
        rid,
        sym,
        None,
        period,
        Decimal(promoter),
        Decimal(100) - Decimal(promoter),
        None,
        DAY,
        when,
        False,
        None,
    )


@pytest.fixture
def world(conn, pg_url, tmp_path):
    _, a, b = make_env(conn)
    for i, d in enumerate((date(2026, 11, 12), date(2026, 11, 13), date(2026, 11, 16))):
        bar(conn, a, d, 100, 1000, (500, 500, 900)[i])  # AAA: delivery 50, 50, 90
        bar(conn, b, d, 10, 5000, 1000)
    n.store_shareholding(
        conn, [sh("1", "AAA", date(2026, 6, 30), 50), sh("2", "AAA", date(2026, 9, 30), 52)], NOW
    )
    for rid, fii, dii in (("1", "10", "20"), ("2", "12", "19")):
        n.store_split(
            conn,
            rid,
            {
                "fii_pct": Decimal(fii),
                "dii_pct": Decimal(dii),
                "mf_pct": Decimal(5),
                "insurance_pct": None,
                "retail_pct": Decimal(8),
            },
            NOW,
        )
    n.store_deals(
        conn,
        [
            ("bulk", DAY, "AAA", "FUND", "BUY", Decimal(1_000_000), Decimal(200), None),
            ("block", DAY, "AAA", "X", "SELL", Decimal(100_000), Decimal(200), None),
        ],
        NOW,
    )
    ins = (
        "1",
        "AAA",
        "P",
        "Promoters",
        "Buy",
        "Market",
        "Equity",
        Decimal(10),
        Decimal(30_000_000),
        None,
        None,
        None,
        Decimal("52"),
        None,
        None,
        None,
        datetime(2026, 11, 16, 10, 0, tzinfo=UTC),
        None,
    )
    n.store_insider(
        conn,
        [ins, ("2", *ins[1:4], "Sell", *ins[5:7], Decimal(1), Decimal(5_000_000), *ins[9:])],
        NOW,
    )
    n.store_fii_dii(
        conn,
        [
            (DAY, "FII", Decimal(10), Decimal(4), Decimal(6)),
            (DAY, "DII", Decimal(3), Decimal(5), Decimal(-2)),
        ],
        NOW,
    )
    conn.commit()
    return TestClient(open_app(pg_url, tmp_path)), conn, a
