# ruff: noqa: E501
"""The screener's smart-money fields, computed from the NSE tables."""

from decimal import Decimal

import pytest

from algo.screener import engine, smart_money
from tests.integration.conftest import DAY

pytestmark = pytest.mark.integration


def test_the_screener_fields_match_the_rules_in_the_data(world):
    _, conn, a = world
    got = smart_money.compute(conn, DAY, {"AAA": a})[a]
    assert got["delivery_pct"] == 90 and got["delivery_pct_20d"] == Decimal(190) / 3
    assert got["delivery_vs_avg"] == 90 / (Decimal(190) / 3)
    assert got["promoter_pct"] == 52 and got["promoter_change"] == 2
    assert (
        got["fii_change"] == 2
        and got["dii_change"] == -1
        and got["mf_change"] == 0
        and got["retail_pct"] == 8
    )
    assert (
        got["insider_net_90d"] == Decimal("2.5") and got["insider_buys_90d"] == 1
    )  # 3 crore bought, 0.5 sold
    assert got["deal_net_30d"] == Decimal("18")  # 20 crore bought, 2 crore sold
    assert "fii_change" not in smart_money.compute(conn, DAY, {"BBB": a + 1}).get(
        a, {}
    )  # a stock with no filings has no holder fields


def test_every_smart_money_field_is_known_to_the_engine(world):
    _, conn, a = world
    assert set(smart_money.compute(conn, DAY, {"AAA": a})[a]) <= set(engine.FIELDS)
    assert {k for k, f in engine.FIELDS.items() if f.kind == "smart_money"} == {
        f[0] for f in engine.SMART_MONEY_FIELDS
    }
