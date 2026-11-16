"""Which days a backtest decides on: every trading day, but not a special session where hardly any stock traded."""

from datetime import date, timedelta

from algo.backtest.engine import real_sessions

D0 = date(2017, 10, 16)


def test_a_muhurat_hour_with_a_few_stocks_is_not_a_session_and_a_normal_day_is():
    days = [D0 + timedelta(days=i) for i in range(5)]
    book = {i: list(days) for i in range(100)}
    for i in range(4, 100):
        book[i].remove(days[3])  # only 4 of 100 traded on day 3
    assert real_sessions(book, days[0], days[-1]) == [d for d in days if d != days[3]]


def test_a_thin_but_real_day_and_the_window_edges_are_kept_and_nothing_gives_nothing():
    days = [D0 + timedelta(days=i) for i in range(4)]
    book = {i: list(days) for i in range(100)}
    for i in range(20, 100):
        book[i].remove(days[2])  # 20 of 100: thin, not special
    assert real_sessions(book, days[1], days[2]) == [days[1], days[2]]
    assert real_sessions(book, date(2030, 1, 1), date(2030, 2, 1)) == []
