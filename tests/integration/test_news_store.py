# ruff: noqa: E501
"""Storing news: new headlines are added with sentiment and the stocks they name, a repeat adds nothing and changes nothing."""

from datetime import UTC, datetime

import pytest

from algo.data import news
from tests.unit.data.test_news import RSS, STOCKS

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 17, 6, 0, tzinfo=UTC)


def test_new_items_are_stored_once_with_their_sentiment_and_first_seen_time(conn):
    from algo.data.store.migrate import migrate

    migrate(conn)
    items = news.parse_rss(RSS, "feed")
    names = news.name_index(STOCKS)
    assert news.store(conn, items, names, list(STOCKS), NOW) == 2
    assert (
        news.store(conn, items, names, list(STOCKS), datetime(2026, 11, 18, tzinfo=UTC)) == 0
    )  # a repeat adds nothing...
    title, published, seen, sentiment, hits = conn.execute(
        "SELECT title, published_at, first_seen_at, sentiment, hits FROM news_item WHERE url='https://ex.com/a'"
    ).fetchone()
    assert (
        seen == NOW and published < seen and sentiment > 0 and hits >= 2
    )  # ...and the first sighting time is kept
