# ruff: noqa: E501
"""The smart-money inputs of the score history are what was KNOWN on each day: a filing broadcast later, or a deal dated later, is invisible."""

from datetime import timedelta

import pytest

from algo.screener import history
from tests.integration.conftest import DAY

pytestmark = pytest.mark.integration


def test_deals_and_insider_trades_count_only_from_the_day_they_happened(world):
    _, conn, _ = world
    before = history.smart_fields(conn, [DAY - timedelta(days=1)])
    assert ("AAA" not in {s for _, s in before}) or "deal_net_30d" not in before.get(
        (DAY - timedelta(days=1), "AAA"), {}
    )
    got = history.smart_fields(conn, [DAY])[(DAY, "AAA")]
    assert got["deal_net_30d"] == pytest.approx(18) and got["insider_net_90d"] == pytest.approx(
        2.5
    )  # same figures the live fields give


def test_a_shareholding_filing_is_invisible_until_it_was_broadcast(world):
    _, conn, _ = world
    on_the_day = history.smart_fields(conn, [DAY])[(DAY, "AAA")]
    assert (
        "promoter_pct" not in on_the_day and "fii_change" not in on_the_day
    )  # broadcast the next day
    after = history.smart_fields(conn, [DAY + timedelta(days=1)])[(DAY + timedelta(days=1), "AAA")]
    assert (
        after["promoter_pct"] == 52
        and after["promoter_change"] == 2
        and after["fii_change"] == 2
        and after["dii_change"] == -1
    )
