# ruff: noqa: E501
"""Loading the score history for a run: only the asked-for stocks, nothing after the end date, and one weekly row before the start so the first decision day has a score."""

from datetime import date

import pytest

from algo.research import score_book
from tests.support.bt import make_env

pytestmark = pytest.mark.integration


def test_rows_are_loaded_for_the_stocks_asked_up_to_the_end_date_only(conn):
    _, a, b = make_env(conn)
    for iid, day, s in (
        (a, date(2024, 3, 1), 60),
        (a, date(2024, 3, 8), 70),
        (a, date(2024, 3, 15), 99),
        (b, date(2024, 3, 8), 55),
    ):
        conn.execute(
            "INSERT INTO stock_score_history (day, instrument_id, score, trend) VALUES (%s,%s,%s,%s)",
            (day, iid, s, 40.0),
        )
    book = score_book.load(conn, [a], date(2024, 3, 9), date(2024, 3, 10))
    assert (
        book.fields(a, date(2024, 3, 9))["score"] == 70
    )  # the row before the start serves the first decision day
    assert (
        book.fields(a, date(2024, 3, 20)) == {}
    )  # the 15th is after the end date: it was never loaded, so the future cannot leak
    assert book.fields(b, date(2024, 3, 9)) == {}  # a stock that was not asked for
    assert book.digest() == score_book.load(conn, [a], date(2024, 3, 9), date(2024, 3, 10)).digest()


def test_the_market_zone_is_loaded_with_the_scores_up_to_the_end_date_only(conn):
    _, a, _ = make_env(conn)
    for day, fg, trend, vol in (
        (date(2024, 3, 8), 30, "BEAR", "STRESSED"),
        (date(2024, 3, 9), 70, "BULL", "CALM"),
        (date(2024, 3, 15), 99, "BULL", "CALM"),
        (date(2024, 3, 7), None, "UNKNOWN", "UNKNOWN"),
    ):
        conn.execute(
            "INSERT INTO market_regime_daily (day, universe, advancers, decliners, unchanged, n50, above50, n200, above200, highs, lows, fear_greed, trend, volatility, computed_at) VALUES (%s,100,50,50,0,100,50,100,50,5,5,%s,%s,%s,now())",
            (day, fg, trend, vol),
        )
    book = score_book.load(conn, [a], date(2024, 3, 9), date(2024, 3, 10))
    assert book.fields(a, date(2024, 3, 8)) == {
        "mkt_fear_greed": 30,
        "mkt_bull": 0,
        "mkt_stressed": 1,
    }
    assert book.fields(a, date(2024, 3, 9)) == {
        "mkt_fear_greed": 70,
        "mkt_bull": 1,
        "mkt_stressed": 0,
    }
    assert (
        book.market_on(date(2024, 3, 7)) == {}
    )  # an UNKNOWN regime with no fear/greed is no reading at all
    assert book.market_on(date(2024, 3, 20)) == {}  # the 15th (after the end date) was never loaded
