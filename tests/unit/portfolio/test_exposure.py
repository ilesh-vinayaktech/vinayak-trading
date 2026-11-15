from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from algo.portfolio.exposure import Position, aggregate_book
from algo.risk.checks import check
from algo.risk.limits import Limits
from algo.risk.model import Day, Market, OrderRequest, Side

SECTORS = {1: "BANKS", 2: "BANKS", 3: "IT", 4: None}


def book(positions, instrument=1, **kw):
    return aggregate_book(
        positions, instrument_id=instrument, sector_of=SECTORS, cash=D(500_000), **kw
    )


def test_two_strategies_holding_the_same_stock_are_summed():
    b = book(
        {
            "S1": {1: Position(100, D(60_000))},
            "S2": {1: Position(50, D(30_000)), 3: Position(10, D(5_000))},
        }
    )
    assert (b.position_qty, b.instrument_value) == (150, D(90_000))
    assert (
        b.gross_value == D(95_000) and b.net_value == D(95_000) and b.margin_available == D(500_000)
    )


def test_sector_value_sums_every_instrument_in_the_orders_sector_across_strategies():
    pos = {
        "S1": {1: Position(100, D(60_000))},
        "S2": {2: Position(10, D(20_000)), 3: Position(10, D(5_000))},
    }
    assert book(pos, instrument=1).sector_value == D(80_000)  # banks: 60k + 20k, not IT
    assert book(pos, instrument=3).sector_value == D(5_000)
    assert book(pos, instrument=4).sector_value == D(0)  # no known sector: contributes to none


def test_a_long_and_a_short_of_the_same_stock_net_before_gross_is_taken():
    b = book(
        {
            "S1": {1: Position(100, D(60_000))},
            "S2": {1: Position(-100, D(-60_000)), 3: Position(5, D(1_000))},
        }
    )
    assert b.position_qty == 0 and b.instrument_value == D(0)
    assert b.gross_value == D(1_000) and b.net_value == D(1_000)
    short = book({"S1": {1: Position(-10, D(-6_000))}, "S2": {3: Position(5, D(1_000))}})
    assert short.gross_value == D(7_000) and short.net_value == D(-5_000)


def test_empty_and_unknown_instrument_and_open_orders():
    b = book({}, open_orders=3)
    assert (b.position_qty, b.gross_value, b.net_value, b.sector_value, b.open_orders) == (
        0,
        D(0),
        D(0),
        D(0),
        3,
    )
    assert book({"S1": {1: Position(1, D(10))}}, instrument=99).position_qty == 0


def test_a_position_whose_quantity_and_value_disagree_is_refused():
    for bad in (
        Position(10, D(-5)),
        Position(-10, D(5)),
        Position(0, D(5)),
        Position(0, D(-5)),
        Position(5, D(0)),
        Position(-5, D(0)),
    ):
        with pytest.raises(ValueError, match="disagree"):
            book({"S1": {1: bad}})
    book({"S1": {1: Position(0, D(0))}})  # flat is fine


def test_the_summed_book_trips_a_limit_neither_strategy_would_trip_alone():
    limits = Limits(max_instrument_value=D(100_000))
    request = OrderRequest("S2", 1, Side.BUY, 10, None)
    market = Market(ltp=D(600))
    alone = book({"S1": {1: Position(100, D(60_000))}, "S2": {}})
    both = book({"S1": {1: Position(100, D(60_000))}, "S2": {1: Position(60, D(36_000))}})
    now = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)
    assert "INSTRUMENT_LIMIT" not in check(request, market, alone, Day(), limits, now).codes
    assert "INSTRUMENT_LIMIT" in check(request, market, both, Day(), limits, now).codes


def test_defaults_types_and_unknown_sector_positions():
    empty = book({})
    assert (
        empty.open_orders == 0
        and empty.instrument_value == D(0)
        and isinstance(empty.gross_value, D)
        and isinstance(empty.net_value, D)
        and isinstance(empty.sector_value, D)
    )
    held_unknown = book({"S1": {4: Position(10, D(7_000)), 2: Position(1, D(100))}}, instrument=4)
    assert held_unknown.sector_value == D(0) and held_unknown.instrument_value == D(
        7_000
    )  # an unknown sector never adds up
    assert book({"S1": {2: Position(1, D(100))}}, instrument=99).instrument_value == D(0)
