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
