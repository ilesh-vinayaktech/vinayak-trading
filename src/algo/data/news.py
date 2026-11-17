# ruff: noqa: E501
"""Market news from public RSS feeds, with a simple sentiment reading (TODO 6.7).

Only the headline, the feed's own summary, the link and the publish time are kept (never article text). Every item keeps the time it was published AND the time we first
saw it, so nothing can be used before it was known. The raw feed goes to the lake before anything is read from it. Feeds are untrusted internet XML: a document type or entity
declaration is refused before parsing.

Sentiment is a crude word list (see POSITIVE / NEGATIVE): each hit counts +1/-1 (strong words 2), a negation (not, no, fails to ...) in the three words before flips it, and the
score is s/(|s|+2) in (-1, 1); an item with no word from the list has NO score (unknown, not neutral). It has never been checked against what markets did next, because there is
no news history to check against yet: it is a mood gauge to look at, not a signal. Stock names found in the HEADLINE (not the summary, which names too many bystanders) are matched to listed companies only when the name is unambiguous."""

from __future__ import annotations

import hashlib
import html
import re
import urllib.request
import xml.etree.ElementTree as ET  # noqa: S405  (DOCTYPE and ENTITY are refused before parsing)
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import psycopg

FEEDS = {
    "economictimes": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "livemint": "https://www.livemint.com/rss/markets",
    "business-standard": "https://www.business-standard.com/rss/markets-106.rss",
    "businessline": "https://www.thehindubusinessline.com/markets/feeder/default.rss",
}
MAX_BYTES = 3_000_000
TIMEOUT_S = 20
STRONG_POS = {"surge", "surges", "soar", "soars", "record high", "all-time high"}
STRONG_NEG = {
    "plunge",
    "plunges",
    "crash",
    "crashes",
    "tumble",
    "tumbles",
    "slump",
    "slumps",
    "fraud",
    "default",
    "bankruptcy",
    "rout",
}
POSITIVE = {"rally", "rallies", "jump", "jumps", "gain", "gains", "rise", "rises", "rose", "climb", "climbs", "upbeat", "bullish", "strong", "beat", "beats", "outperform", "upgrade", "upgrades", "profit", "growth", "recovery", "rebound", "rebounds", "boost", "optimism", "inflows", "buying", "breakout", "robust", "expansion", "wins", "order win", "higher", "advance", "advances", "positive", "improve", "improves", "record", "dividend", "bonus", "buy"}  # fmt: skip
NEGATIVE = {"fall", "falls", "fell", "slide", "slides", "sink", "sinks", "drop", "drops", "decline", "declines", "bearish", "weak", "weakness", "miss", "misses", "downgrade", "downgrades", "loss", "losses", "selloff", "sell-off", "outflows", "selling", "fear", "fears", "worry", "worries", "concern", "concerns", "slowdown", "recession", "war", "tariff", "tariffs", "penalty", "probe", "cut", "cuts", "layoffs", "lower", "volatile", "volatility", "jitters", "pressure", "negative", "warning", "warns", "sell", "debt"}  # fmt: skip
NEGATIONS = {"not", "no", "never", "without", "fails", "failed", "unlikely", "hardly", "nor"}
GENERIC = {"india", "indian", "bank", "power", "steel", "gas", "oil", "motors", "finance", "capital", "industries", "global", "international", "technologies", "energy", "services", "life", "general", "foods", "pharma", "chemicals", "textiles", "projects", "infra", "infrastructure", "securities", "holdings", "investments", "enterprises", "ventures", "systems", "solutions", "media", "cement", "paper", "sugar", "metal", "metals", "auto", "home", "health", "care", "digital", "network", "networks", "retail", "trade", "trading", "star", "sun", "new", "first", "universal", "national", "state", "bharat", "hindustan", "tata", "adani", "birla", "mahindra"}  # fmt: skip
NOT_STOCKS = {
    "NIFTY",
    "SENSEX",
    "RBI",
    "SEBI",
    "FII",
    "DII",
    "FPI",
    "IPO",
    "GDP",
    "NSE",
    "BSE",
    "ETF",
    "USA",
    "EPS",
    "NFL",
    "NBA",
    "MSME",
    "GST",
    "FDI",
    "CPI",
    "WPI",
    "IMF",
    "OPEC",
    "AI",
}
SUFFIX = re.compile(r"\b(limited|ltd|pvt|private|company|co|corporation|corp|inc|the)\b\.?", re.I)
TAG = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Item:
    item_id: str
    source: str
    title: str
    summary: str
    url: str
    published_at: datetime


def clean(text: str | None) -> str:
    return " ".join(html.unescape(TAG.sub(" ", text or "")).split())


def parse_rss(raw: bytes, source: str) -> list[Item]:
    """The items of an RSS 2.0 feed; an item with no link, title or readable time is skipped; a DOCTYPE or ENTITY declaration refuses the whole document."""
    if re.search(rb"<!(DOCTYPE|ENTITY)", raw[:10_000], re.I):
        raise ValueError("feed contains a DOCTYPE or ENTITY declaration")
    out: list[Item] = []
    for node in ET.fromstring(raw).iter("item"):  # noqa: S314  (declarations refused above)
        url, title = clean(node.findtext("link")), clean(node.findtext("title"))
        when = node.findtext("pubDate") or node.findtext("{http://purl.org/dc/elements/1.1/}date")
        if not url or not title or not when:
            continue
        try:
            at = parsedate_to_datetime(when)
        except (TypeError, ValueError):
            continue
        at = at.replace(tzinfo=UTC) if at.tzinfo is None else at.astimezone(UTC)
        out.append(
            Item(
                hashlib.sha1(url.encode()).hexdigest(),
                source,
                title,
                clean(node.findtext("description"))[:600],
                url,
                at,
            )
        )
    return out


def sentiment(text: str) -> tuple[float | None, int]:
    """(score in (-1, 1) or None when no word of the list appears, number of words that counted)."""
    low = text.lower()
    total, hits = 0.0, 0
    for phrase in (p for p in STRONG_POS if " " in p):
        if phrase in low:
            total, hits, low = total + 2, hits + 1, low.replace(phrase, " ")
    words = re.findall(r"[a-z][a-z-]*", low)
    for i, w in enumerate(words):
        weight = 2.0 if w in STRONG_POS or w in STRONG_NEG else 1.0
        sign = (
            1 if w in POSITIVE or w in STRONG_POS else -1 if w in NEGATIVE or w in STRONG_NEG else 0
        )
        if sign == 0:
            continue
        if any(x in NEGATIONS for x in words[max(0, i - 3) : i]):
            sign = -sign
        total += sign * weight
        hits += 1
    return (None, 0) if hits == 0 else (total / (abs(total) + 2), hits)


def name_index(stocks: Mapping[str, tuple[str, str | None]]) -> dict[str, str]:
    """{lowercase phrase: symbol} from {symbol: (symbol, name)}. A phrase that fits two stocks, or is a single common word, is dropped."""
    seen: dict[str, set[str]] = {}
    for sym, (_, name) in stocks.items():
        if not name:
            continue
        phrase = " ".join(re.sub(r"[^a-z0-9& ]", " ", SUFFIX.sub(" ", name.lower())).split())
        words = phrase.split()
        if not words or (len(words) == 1 and (words[0] in GENERIC or len(words[0]) < 6)):
            continue
        seen.setdefault(phrase, set()).add(sym)
    return {p: next(iter(s)) for p, s in seen.items() if len(s) == 1}


def match_symbols(text: str, names: Mapping[str, str], symbols: Sequence[str] = ()) -> list[str]:
    """Stocks named in the text: a company name as a whole phrase, or a ticker (3 letters or more) written in capitals."""
    low = " " + " ".join(re.sub(r"[^a-z0-9& ]", " ", text.lower()).split()) + " "
    found = {sym for phrase, sym in names.items() if f" {phrase} " in low}
    known = set(symbols) - NOT_STOCKS
    found |= {t for t in re.findall(r"\b[A-Z][A-Z0-9&]{2,}\b", text) if t in known}
    return sorted(found)


def fetch(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; market-news-reader)",
            "Accept": "application/rss+xml, application/xml, text/xml",
        },
    )  # noqa: S310
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:  # noqa: S310
        data: bytes = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("feed larger than the limit")
    return data


def store(
    conn: psycopg.Connection,
    items: Sequence[Item],
    names: Mapping[str, str],
    symbols: Sequence[str],
    now: datetime,
) -> int:
    """Insert new items (an item already stored is left as it was). Returns the number added."""
    added = 0
    for it in items:
        text = f"{it.title}. {it.summary}"
        score, hits = sentiment(text)
        cur = conn.execute(
            "INSERT INTO news_item (item_id, source, title, summary, url, published_at, first_seen_at, sentiment, hits, symbols) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (item_id) DO NOTHING",
            (
                it.item_id,
                it.source,
                it.title,
                it.summary,
                it.url,
                it.published_at,
                now,
                score,
                hits,
                match_symbols(it.title, names, symbols),
            ),
        )
        added += cur.rowcount
    return added
