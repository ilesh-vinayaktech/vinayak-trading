"""The score as known on a day: the newest row on or before it, not too old, nothing from the future."""

from datetime import date
from decimal import Decimal as D

from algo.strategies.scorebook import MAX_AGE_DAYS, ScoreBook

ROWS = {
    1: [
        (date(2024, 3, 1), {"score": 60.0, "score_trend": 70.5, "setup": 1.0}),
        (date(2024, 3, 8), {"score": 75.0}),
    ]
}


def test_the_newest_row_on_or_before_the_day_is_used():
    b = ScoreBook(ROWS)
    assert b.fields(1, date(2024, 3, 8)) == {"score": D("75.0")}  # the day itself counts
    assert b.fields(1, date(2024, 3, 10)) == {"score": D("75.0")}
    assert b.fields(1, date(2024, 3, 5)) == {
        "score": D("60.0"),
        "score_trend": D("70.5"),
    }  # a field that is not a numeric score field ("setup") is dropped


def test_a_row_from_the_future_is_invisible_and_so_is_any_stock_without_rows():
    b = ScoreBook(ROWS)
    assert b.fields(1, date(2024, 2, 29)) == {}  # before the first row: nothing, not the first row
    assert b.fields(2, date(2024, 3, 8)) == {}
    assert ScoreBook({}).fields(1, date(2024, 3, 8)) == {}


def test_a_row_older_than_the_limit_is_not_used_so_a_stock_that_lost_its_score_does_not_keep_it():
    b = ScoreBook(ROWS)
    assert b.fields(1, date(2024, 3, 8 + MAX_AGE_DAYS)) != {}
    assert b.fields(1, date(2024, 3, 8 + MAX_AGE_DAYS + 1)) == {}


def test_the_digest_names_exactly_the_rows_held_so_a_rebuilt_history_is_detectable():
    a = ScoreBook(ROWS).digest()
    assert a == ScoreBook({1: list(ROWS[1])}).digest() and len(a) == 64
    changed = {1: [ROWS[1][0], (date(2024, 3, 8), {"score": 75.1})]}
    assert ScoreBook(changed).digest() != a
    assert ScoreBook({}).digest() != a
