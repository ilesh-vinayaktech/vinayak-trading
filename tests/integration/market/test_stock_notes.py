# ruff: noqa: E501
"""The notes for a batch of stocks from the database: chart facts, headlines, announced actions, deals and insider trades, each only inside its own time window."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from algo.market.stock_notes import MAX_IDS, load_bars, notes_for
from tests.integration.market.test_breadth import DAYS, env  # noqa: F401  (env is a fixture)

pytestmark = pytest.mark.integration
NOW = datetime.combine(DAYS[-1] + timedelta(days=3), datetime.min.time(), UTC).replace(
    hour=5
)  # a Monday morning, after the last stored bar


def kinds(notes, iid):
    return [n.kind for n in notes.get(iid, [])]


def test_bars_come_back_oldest_first_with_delivery_percentage_and_stop_at_a_split(env):  # noqa: F811
    conn, ids = env
    b = load_bars(conn, ids["A"])
    assert (
        b["day"] == DAYS[-300:][-len(b["day"]) :]
        and len(b["close"]) == 300
        and b["delivery_pct"][-1] is None
    )
    conn.execute(
        "INSERT INTO corporate_action (instrument_id,ex_date,kind,status,num,den,reason,subject,knowledge_time,knowledge_time_source,source,raw_checksum,ingested_at) VALUES (%s,%s,'split','ok',1,2,'r','t',now(),'ex_date_proxy','nse','x',now())",
        (ids["A"], DAYS[-10]),
    )
    assert (
        len(load_bars(conn, ids["A"])["close"]) == 10
    )  # only the bars since the split are comparable


def test_a_rising_stock_with_live_prices_gets_chart_notes_and_a_flat_one_none(env):  # noqa: F811
    conn, ids = env
    conn.execute(
        "INSERT INTO live_quote (instrument_id, ltp, day_open, day_high, day_low, volume, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (ids["A"], D("500"), D("480"), D("505"), D("479"), 90_000, NOW),
    )
    got = notes_for(conn, [ids["A"], ids["C"]], NOW)
    assert {"new_high", "gap_up"} <= set(
        kinds(got, ids["A"])
    )  # a stock that rose every day, now far above its high
    assert ids["C"] not in got  # a flat stock has nothing to say


def test_a_live_day_replaces_a_stored_bar_for_today_instead_of_counting_it_twice(env):  # noqa: F811
    conn, ids = env
    today_noon = datetime.combine(DAYS[-1], datetime.min.time(), UTC).replace(hour=6)
    conn.execute(
        "INSERT INTO live_quote (instrument_id, ltp, day_open, day_high, day_low, volume, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (ids["A"], D("1"), D("1"), D("1"), D("1"), 1, today_noon),
    )
    got = notes_for(
        conn, [ids["A"]], today_noon
    )  # the session of the last stored bar: that bar must give way to the live quote
    assert "new_low" in kinds(
        got, ids["A"]
    )  # the live price of 1 against a year of 100+ is the new low, not "a bar then another"


def test_news_actions_deals_and_insiders_each_appear_only_inside_their_window(env):  # noqa: F811
    conn, ids = env
    iid = ids["A"]
    conn.execute(
        "INSERT INTO news_item (item_id, source, title, summary, url, published_at, first_seen_at, sentiment, hits, symbols) VALUES ('n1','x','A wins a big order','',%s,%s,%s,0.8,2,%s)",
        ("u1", NOW - timedelta(hours=5), NOW, ["A"]),
    )
    conn.execute(
        "INSERT INTO news_item (item_id, source, title, summary, url, published_at, first_seen_at, sentiment, hits, symbols) VALUES ('n2','x','Old story','',%s,%s,%s,-0.9,2,%s)",
        ("u2", NOW - timedelta(days=9), NOW, ["A"]),
    )
    conn.execute(
        "INSERT INTO corporate_action_upcoming (instrument_id, ex_date, kind, status, amount, subject, fetched_at) VALUES (%s,%s,'dividend','ok',5,'Dividend - Rs 5',%s)",
        (iid, (NOW + timedelta(days=4)).date(), NOW),
    )
    conn.execute(
        "INSERT INTO corporate_action_upcoming (instrument_id, ex_date, kind, status, subject, fetched_at) VALUES (%s,%s,'bonus','ok','Bonus 1:1',%s)",
        (iid, (NOW + timedelta(days=60)).date(), NOW),
    )
    conn.execute(
        "INSERT INTO nse_bulk_block_deal (kind, trade_date, symbol, client, side, quantity, price, ingested_at) VALUES ('bulk',%s,'A','BIG FUND','BUY',500000,101.5,%s)",
        ((NOW - timedelta(days=1)).date(), NOW),
    )
    conn.execute(
        "INSERT INTO nse_bulk_block_deal (kind, trade_date, symbol, client, side, quantity, price, ingested_at) VALUES ('block',%s,'A','OLD FUND','SELL',1,1,%s)",
        ((NOW - timedelta(days=30)).date(), NOW),
    )
    for did, kind, value in (("i1", "Buy", 30_000_000), ("i2", "Sell", 10_000_000)):
        conn.execute(
            "INSERT INTO nse_insider_trade (did, symbol, person, person_category, transaction_type, quantity, value, broadcast_at, ingested_at) VALUES (%s,'A','P','Promoters',%s,1,%s,%s,%s)",
            (did, kind, value, NOW - timedelta(days=2), NOW),
        )
    got = {n.kind: n for n in notes_for(conn, [iid], NOW)[iid]}
    assert (
        got["news"].tone == "good"
        and got["news"].text == "1 headline, mostly positive"
        and "wins a big order" in (got["news"].detail or "")
    )  # the 9-day-old story is outside the window
    assert (
        got["action"].text == "Ex-dividend in 4d" and got["action"].tone == "warn"
    )  # the bonus 60 days out is outside it
    assert got["deal"].tone == "good" and "BIG FUND bought 500,000" in (got["deal"].detail or "")
    assert (
        got["insider"].text == "Insiders buying ₹2.0 cr" and got["insider"].tone == "good"
    )  # bought 3 cr, sold 1 cr: net 2 cr
    assert [n.rank for n in notes_for(conn, [iid], NOW)[iid]] == sorted(
        n.rank for n in notes_for(conn, [iid], NOW)[iid]
    )


def test_balanced_insiders_say_nothing_and_a_batch_is_capped(env):  # noqa: F811
    conn, ids = env
    for did, kind in (("i1", "Buy"), ("i2", "Sell")):
        conn.execute(
            "INSERT INTO nse_insider_trade (did, symbol, person, person_category, transaction_type, quantity, value, broadcast_at, ingested_at) VALUES (%s,'A','P','x',%s,1,5000000,%s,%s)",
            (did, kind, NOW - timedelta(days=1), NOW),
        )
    assert "insider" not in kinds(notes_for(conn, [ids["A"]], NOW), ids["A"])
    assert (
        notes_for(conn, list(range(1000, 1000 + MAX_IDS + 40)), NOW) == {}
    )  # unknown ids are ignored, however many are asked
