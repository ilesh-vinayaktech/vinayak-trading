# ruff: noqa: E501
"""The NSE smart-money API and the screener fields built from the same tables."""

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from tests.support.portal import open_app

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 17, 13, 0, tzinfo=UTC)
DAY = date(2026, 11, 16)


def test_flows_most_active_delivery_deals_insider(world):
    c, _, _ = world
    assert c.get("/api/nse/flows").json()["rows"] == [
        {
            "date": "2026-11-16",
            "fii_buy": 10.0,
            "fii_sell": 4.0,
            "fii_net": 6.0,
            "dii_buy": 3.0,
            "dii_sell": 5.0,
            "dii_net": -2.0,
        }
    ]
    ma = c.get("/api/nse/most-active", params={"by": "volume"}).json()
    assert ma["day"] == "2026-11-16" and [r["symbol"] for r in ma["rows"]] == ["BBB", "AAA"]
    dl = c.get("/api/nse/delivery", params={"min_volume": 0}).json()
    assert [(r["symbol"], r["delivery_pct"]) for r in dl["rows"]] == [("AAA", 90.0), ("BBB", 20.0)]
    assert [
        (r["kind"], r["side"], r["value_cr"]) for r in c.get("/api/nse/deals").json()["rows"]
    ] == [("bulk", "BUY", 20.0), ("block", "SELL", 2.0)]
    assert c.get("/api/nse/most-active", params={"by": "price"}).status_code == 422


def test_one_stock_has_delivery_holdings_insider_and_deals(world):
    c, _, a = world
    body = c.get(f"/api/nse/instrument/{a}").json()
    assert body["symbol"] == "AAA" and [r["delivery_pct"] for r in body["delivery"]] == [
        90.0,
        50.0,
        50.0,
    ]
    assert [(h["period_end"], h["promoter"], h["fii"]) for h in body["holdings"]] == [
        ("2026-09-30", 52.0, 12.0),
        ("2026-06-30", 50.0, 10.0),
    ]
    assert len(body["insider"]) == 2 and len(body["deals"]) == 2
    assert c.get("/api/nse/instrument/999999").status_code == 404


def test_an_empty_database_gives_empty_lists_not_errors(conn, pg_url, tmp_path):
    from algo.data.store.migrate import migrate

    migrate(conn)
    conn.commit()
    c = TestClient(open_app(pg_url, tmp_path))
    for path in ("flows", "most-active", "delivery", "deals", "insider"):
        assert c.get(f"/api/nse/{path}").json()["rows"] == [], path


def test_list_rows_carry_the_instrument_id_for_linking(world):
    c, _, a = world
    assert [r["id"] for r in c.get("/api/nse/delivery", params={"min_volume": 0}).json()["rows"]][
        0
    ] == a
    assert {r["id"] for r in c.get("/api/nse/deals").json()["rows"]} == {a}
    assert {r["id"] for r in c.get("/api/nse/insider").json()["rows"]} == {a}
    assert c.get("/api/nse/most-active").json()["rows"][0]["id"] in (a, a + 1)
