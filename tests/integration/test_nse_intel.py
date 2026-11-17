# ruff: noqa: E501
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from algo.data import nse_intel as n
from tests.support.bt import make_env

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 17, 13, 0, tzinfo=UTC)
DAY = date(2026, 11, 16)


def test_store_is_idempotent_and_counts_only_new(conn):
    make_env(conn)
    deals = [("bulk", DAY, "AAA", "C", "BUY", Decimal(10), Decimal("5"), None)]
    assert n.store_deals(conn, deals, NOW) == 1
    assert (
        n.store_deals(
            conn, deals + [("block", DAY, "AAA", "C", "BUY", Decimal(10), Decimal("5"), None)], NOW
        )
        == 1
    )
    fii = [(DAY, "FII", Decimal(1), Decimal(2), Decimal(-1))]
    assert (n.store_fii_dii(conn, fii, NOW), n.store_fii_dii(conn, fii, NOW)) == (1, 0)
    ins = [
        (
            "1",
            "AAA",
            "P",
            None,
            "Buy",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            NOW,
            None,
        )
    ]
    assert (n.store_insider(conn, ins, NOW), n.store_insider(conn, ins, NOW)) == (1, 0)
    sh = [
        ("9", "AAA", None, date(2026, 9, 30), Decimal(50), Decimal(50), None, DAY, NOW, False, None)
    ]
    assert (n.store_shareholding(conn, sh, NOW), n.store_shareholding(conn, sh, NOW)) == (1, 0)
    assert conn.execute("SELECT count(*) FROM nse_bulk_block_deal").fetchone()[0] == 2


def bar(conn, iid, close, volume, deliv, series="EQ", version=1):
    conn.execute(
        "INSERT INTO bar_1d (instrument_id, ts, open, high, low, close, volume, series, delivery_qty, source, dataset_version, ingested_at)"
        " VALUES (%s, '2026-11-16 03:45+00', %s, %s, %s, %s, %s, %s, %s, 'nse', %s, now())",
        (iid, close, close, close, close, volume, series, deliv, version),
    )


def test_delivery_pct_and_most_active_use_latest_version_and_eq_only(conn):
    _, a, b = make_env(conn)
    bar(conn, a, 100, 1000, 900, version=1)
    bar(conn, a, 100, 1000, 400, version=2)  # a correction: the newest version wins
    bar(conn, b, 10, 5000, 4000)
    rows = n.delivery_pct(conn, DAY)
    assert [(r[0], r[4]) for r in rows] == [("BBB", Decimal("80.00")), ("AAA", Decimal("40.00"))]
    assert [r[0] for r in n.delivery_pct(conn, DAY, min_volume=2000)] == ["BBB"]
    assert [r[0] for r in n.most_active(conn, DAY)] == ["AAA", "BBB"]  # 100,000 vs 50,000
    assert [r[0] for r in n.most_active(conn, DAY, by="volume", limit=1)] == ["BBB"]
    assert n.most_active(conn, date(2026, 11, 15)) == []
    with pytest.raises(ValueError, match="by must be"):
        n.most_active(conn, DAY, by="price")


def test_non_eq_series_are_left_out(conn):
    _, a, _ = make_env(conn)
    bar(conn, a, 100, 1000, 900, series="BE")
    assert n.delivery_pct(conn, DAY) == [] and n.most_active(conn, DAY) == []


def test_pending_splits_newest_first_and_failures_are_not_retried(conn):
    make_env(conn)
    rows = [
        ("1", "AAA", None, date(2026, 6, 30), None, None, None, DAY, NOW, False, "u1"),
        ("2", "AAA", None, date(2026, 9, 30), None, None, None, DAY, NOW, False, "u2"),
        (
            "3",
            "BBB",
            None,
            date(2026, 9, 30),
            None,
            None,
            None,
            DAY,
            NOW,
            False,
            None,
        ),  # no file to read
    ]
    n.store_shareholding(conn, rows, NOW)
    assert n.pending_splits(conn, 10) == [("2", "u2"), ("1", "u1")]
    n.store_split(conn, "2", {"fii_pct": Decimal(7)}, NOW)
    n.store_split(conn, "1", None, NOW, "bad XBRL")
    assert n.pending_splits(conn, 10) == []
    assert conn.execute(
        "SELECT fii_pct, split_error FROM nse_shareholding ORDER BY record_id"
    ).fetchall() == [(None, "bad XBRL"), (Decimal(7), None), (None, None)]


def test_pit_index_pending_details_and_a_revision_replaces_the_original(conn):
    make_env(conn)
    at = datetime(2026, 11, 17, 7, tzinfo=UTC)
    orig = ("1", "AAA", "Co", "Regulation 7 (2)", "Original", None, at, "u1")
    assert n.store_pit_index(conn, [orig], NOW) == 1
    assert n.store_pit_index(conn, [orig], NOW) == 0
    assert n.pending_pit_details(conn, 10) == [("1", "AAA", at, "u1")]
    trade = n.parse_pit_detail("1", _filing_html("Trust A"), at, "u1")
    assert n.store_insider(conn, trade, NOW) == 1
    n.mark_pit_detail(conn, "1", NOW)
    assert n.pending_pit_details(conn, 10) == []
    rev = ("2", "AAA", "Co", "Regulation 7 (2)", "Revision", "1", at, "u2")
    assert n.store_pit_index(conn, [rev], NOW) == 1
    assert conn.execute(
        "SELECT superseded FROM nse_insider_filing WHERE app_id='1'"
    ).fetchone() == (True,)
    assert conn.execute("SELECT count(*) FROM nse_insider_trade").fetchone() == (
        0,
    )  # the replaced filing's trades are gone
    assert n.pending_pit_details(conn, 10) == [("2", "AAA", at, "u2")]
    n.mark_pit_detail(conn, "2", NOW, "bad file")
    assert n.pending_pit_details(conn, 10) == []


def _filing_html(who):
    return (
        "<html xmlns:ix='x'>"
        "<ix:nonNumeric name='in-bse-co:Symbol' contextRef='MainI'>AAA</ix:nonNumeric>"
        f"<ix:nonNumeric name='in-bse-co:NameOfThePerson' contextRef='Disclosure1'>{who}</ix:nonNumeric></html>"
    ).encode()
