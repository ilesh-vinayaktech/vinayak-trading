# ruff: noqa: E501
"""RSS news: feeds parsed to UTC items, untrusted XML refused, a word-list sentiment that handles negation and says nothing when no word matches, and
unambiguous stock matching."""

from datetime import UTC, datetime

import pytest

from algo.data import news

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>
<item><title>Sensex surges 900 points as FII inflows return</title><link>https://ex.com/a</link><pubDate>Tue, 17 Nov 2026 10:30:00 +0530</pubDate><description>&lt;p&gt;Markets &lt;b&gt;rally&lt;/b&gt;&lt;/p&gt;</description></item>
<item><title>No date here</title><link>https://ex.com/b</link></item>
<item><title></title><link>https://ex.com/c</link><pubDate>Tue, 17 Nov 2026 10:30:00 GMT</pubDate></item>
<item><title>Naive time</title><link>https://ex.com/d</link><pubDate>Tue, 17 Nov 2026 10:30:00 -0000</pubDate></item>
</channel></rss>"""


def test_items_are_parsed_to_utc_with_markup_removed_and_unreadable_ones_skipped():
    items = news.parse_rss(RSS, "feed")
    assert [i.url for i in items] == ["https://ex.com/a", "https://ex.com/d"]
    a = items[0]
    assert (
        a.published_at == datetime(2026, 11, 17, 5, 0, tzinfo=UTC)
        and a.summary == "Markets rally"
        and a.source == "feed"
    )
    assert items[1].published_at.tzinfo is not None
    assert (
        news.parse_rss(RSS, "feed")[0].item_id == a.item_id
    )  # the id is stable: the same link is the same item


@pytest.mark.parametrize(
    "doc",
    [
        b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x "y">]><rss><channel/></rss>',
        b"<!ENTITY a 'b'><rss/>",
    ],
)
def test_a_feed_with_a_doctype_or_entity_declaration_is_refused(doc):
    with pytest.raises(ValueError, match="DOCTYPE"):
        news.parse_rss(doc, "feed")


@pytest.mark.parametrize(
    ("text", "sign"),
    [
        ("Sensex surges as FII inflows return", 1),
        ("Nifty plunges, selloff deepens on recession fears", -1),
        ("Market does not rally despite upbeat data", -1),  # negation flips 'rally'
        ("Profit growth is not weak", 1),  # negation flips 'weak'
    ],
)
def test_sentiment_has_the_right_sign_and_stays_inside_minus_one_to_one(text, sign):
    score, hits = news.sentiment(text)
    assert score is not None and hits > 0 and -1 < score < 1 and (score > 0) == (sign > 0)


def test_no_word_from_the_list_means_no_score_not_a_neutral_one():
    assert news.sentiment("Board meeting scheduled for Thursday") == (None, 0)
    assert news.sentiment("") == (None, 0)


def test_strong_words_count_double_and_more_evidence_moves_the_score_further():
    a, _ = news.sentiment("shares gain")
    b, _ = news.sentiment("shares surge")
    c, _ = news.sentiment("shares surge and rally on strong profit")
    assert 0 < a < b < c < 1


STOCKS = {"TCS": ("TCS", "Tata Consultancy Services Limited"), "RELIANCE": ("RELIANCE", "Reliance Industries Limited"), "A": ("A", "Bank of India"), "B": ("B", "Bank Of India Ltd"), "ITC": ("ITC", "ITC Limited"), "SBIN": ("SBIN", "State Bank of India"), "X": ("X", "Power")}  # fmt: skip


def test_company_names_and_capitalised_tickers_are_found_and_ambiguous_or_generic_names_are_not():
    names = news.name_index(STOCKS)
    assert "tata consultancy services" in names and "reliance industries" in names
    assert "bank of india" not in names  # two companies share it: dropped, never guessed
    assert "power" not in names  # a single common word
    assert news.match_symbols(
        "Reliance Industries and TCS lead gains; ITC slips", names, list(STOCKS)
    ) == ["ITC", "RELIANCE", "TCS"]
    assert news.match_symbols("RBI and SEBI hold talks on NIFTY", names, list(STOCKS)) == []
    assert news.match_symbols("Tcs is not a ticker in lower case", names, list(STOCKS)) == []
