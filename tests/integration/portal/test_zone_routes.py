# ruff: noqa: E501, F811
"""The market zone route: the latest day with its breadth, the signals ranked greediest first, a year of history oldest first; nothing yet is an empty answer, and
only signed-in people can read it."""

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from tests.integration.portal.test_paper_routes import env, trader  # noqa: F401  (env is a fixture)
from tests.support.bt import add_action
from tests.support.portal import add_user, sign_in

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)
TODAY = date(2026, 11, 11)


def put(conn, day, fg, label, trend, comps=None):
    conn.execute(
        "INSERT INTO market_regime_daily (day, universe, advancers, decliners, unchanged, n50, above50, n200, above200, highs, lows, fear_greed, label, trend, volatility, components, computed_at)"
        " VALUES (%s,1600,900,600,100,1500,600,1400,800,45,12,%s,%s,%s,'NORMAL',%s,%s)",
        (day, fg, label, trend, Jsonb(comps) if comps else None, NOW),
    )


def test_nothing_built_yet_is_an_empty_answer(env):  # noqa: F811
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    assert c.get("/api/market/zone").json() == {"latest": None, "history": [], "drivers": []}


def test_the_latest_day_its_breadth_and_the_signals_ranked_greediest_first(env):  # noqa: F811
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    put(conn, TODAY - timedelta(days=2), 41.0, "Fear", "SIDEWAYS")
    put(conn, TODAY - timedelta(days=1), 52.0, "Neutral", "SIDEWAYS")
    comps = {"momentum": 80.5, "breadth": 20.0, "volatility": 55.0, "stocks_vs_bonds": None}
    put(conn, TODAY, 63.5, "Greed", "BULL", comps)
    got = c.get("/api/market/zone").json()
    assert got["latest"] == {
        "day": "2026-11-11", "age_days": 0, "live": False, "as_of": None, "fear_greed": 63.5, "label": "Greed", "trend": "BULL", "volatility": "NORMAL",
        "universe": 1600, "advancers": 900, "decliners": 600, "unchanged": 100, "pct_above_50": 40.0, "pct_above_200": 57.1,
        "highs": 45, "lows": 12,
    }  # fmt: skip
    assert [d["key"] for d in got["drivers"]] == [
        "momentum",
        "volatility",
        "breadth",
    ]  # the unscored one is left out
    assert got["drivers"][0] == {
        "key": "momentum",
        "name": "Index trend against its 125-day average",
        "score": 80.5,
        "reading": None,  # no live reading: the figure behind the score is not stored
    }
    assert [h["day"] for h in got["history"]] == [
        "2026-11-09",
        "2026-11-10",
        "2026-11-11",
    ]  # oldest first


def test_a_stale_row_says_how_old_it_is_and_unscored_days_stay_out_of_the_history(env):  # noqa: F811
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    put(conn, TODAY - timedelta(days=5), 70.0, "Greed", "BULL")
    put(conn, TODAY - timedelta(days=4), None, None, "UNKNOWN")
    got = c.get("/api/market/zone").json()
    assert got["latest"]["age_days"] == 4 and got["latest"]["fear_greed"] is None
    assert [h["day"] for h in got["history"]] == ["2026-11-06"]


def test_only_signed_in_people_can_read_it(env):  # noqa: F811
    conn, app, clock, _ = env
    add_user(conn, clock, "VIEWER", "viewer@example.com")
    assert sign_in(app, "viewer@example.com").get("/api/market/zone").status_code == 200
    assert TestClient(app).get("/api/market/zone").status_code == 401


def put_index(conn, symbol, drift, n=300):
    x = 1000.0
    for i in range(n):
        x *= 1 + drift
        conn.execute(
            "INSERT INTO index_bar_1d (exchange, symbol, trade_date, open, high, low, close, token, ingested_at) VALUES ('NSE',%s,%s,1,1,1,%s,1,%s)",
            (symbol, TODAY - timedelta(days=n - 1 - i), round(x, 4), NOW),
        )


def test_sectors_come_back_strongest_first_with_their_quadrant_and_nothing_built_is_empty(env):  # noqa: F811
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    assert c.get("/api/market/sectors").json() == {
        "as_of": None,
        "benchmark": "NIFTY 500",
        "sectors": [],
    }
    put_index(conn, "NIFTY 500", 0.0005)
    put_index(conn, "NIFTY BANK", 0.0015)  # keeps beating the benchmark
    put_index(conn, "NIFTY IT", -0.0005)  # keeps losing to it
    got = c.get("/api/market/sectors").json()
    assert got["as_of"] == "2026-11-11" and got["benchmark"] == "NIFTY 500"
    assert [s["name"] for s in got["sectors"]] == ["Bank", "IT"]
    bank, it = got["sectors"]
    assert (
        bank["quadrant"] == "Leading"
        and it["quadrant"] == "Lagging"
        and bank["score"] > it["score"]
    )
    assert bank["above_200"] is True and it["above_200"] is False
    assert (bank["symbol"], bank["now"]) == ("NIFTY BANK", None)  # the feed has not quoted it
    conn.execute(
        "INSERT INTO index_live_quote (token, exchange, symbol, ltp, prev_close, updated_at) VALUES (1,'NSE','NIFTY BANK',62000,62500,%s)",
        (clock.now(),),
    )
    now = {s["name"]: s["now"] for s in c.get("/api/market/sectors").json()["sectors"]}
    assert (now["Bank"]["ltp"], now["Bank"]["prev_close"], round(now["Bank"]["change_pct"], 2)) == (
        62000,
        62500,
        -0.8,
    ) and now["IT"] is None
    assert set(bank) >= {
        "ret_1d",
        "ret_21d",
        "ret_63d",
        "ret_252d",
        "rs_ratio",
        "rs_momentum",
        "close",
    }


def log(conn, day, subject, h, p, live, up=None, realized=None, ev=None):
    conn.execute(
        "INSERT INTO prediction_log (as_of, subject, horizon_days, model_version, live, p_up, evidence, outcome_up, realized) VALUES (%s,%s,%s,'logit-v2-night',%s,%s,%s,%s,%s)",
        (day, subject, h, live, p, Jsonb(ev or []), up, realized),
    )


def test_forecast_with_nothing_logged_is_empty(env):  # noqa: F811
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    assert c.get("/api/market/forecast").json() == {
        "as_of": None,
        "market": [],
        "sectors": [],
        "record": [],
        "misses": [],
        "today": None,
        "overnight": None,
    }


def test_forecast_gives_tonights_probabilities_the_track_record_and_the_biggest_misses(env):  # noqa: F811
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    ev = [{"feature": "momentum", "value": 70.0, "effect": 0.2}]
    log(conn, TODAY, "MARKET", 1, 0.58, True, ev=ev)
    log(conn, TODAY, "MARKET", 5, 0.61, True)
    log(conn, TODAY, "IT", 1, 0.40, True)
    log(conn, TODAY, "IT", 5, 0.45, True)
    log(conn, TODAY, "Bank", 1, 0.55, True)
    for k in range(30):  # a walk-forward history that is no better than guessing
        d = TODAY - timedelta(days=40 + k)
        log(
            conn,
            d,
            "MARKET",
            1,
            0.9 if k == 0 else 0.55,
            False,
            up=k % 2 == 0 and k != 0,
            realized=-0.02 if k == 0 else 0.001,
        )
    got = c.get("/api/market/forecast").json()
    assert got["as_of"] == "2026-11-11"
    assert [(m["horizon_days"], m["p_up"]) for m in got["market"]] == [
        (1, pytest.approx(0.58)),
        (5, pytest.approx(0.61)),
    ] and got["market"][0]["evidence"] == ev
    assert [s["name"] for s in got["sectors"]] == ["Bank", "IT"] and got["sectors"][1][
        "p_5d"
    ] == pytest.approx(0.45)  # most bullish first
    rec = got["record"]
    assert (
        len(rec) == 1
        and rec[0]["live"] is False
        and rec[0]["horizon_days"] == 1
        and rec[0]["n"] == 30
        and rec[0]["beats_guessing"] is False
    )
    assert (
        got["misses"][0]["p_up"] == pytest.approx(0.9) and got["misses"][0]["went_up"] is False
    )  # the most confident wrong call first
    assert "momentum" in got["labels"]


def test_forecast_needs_a_signed_in_user(env):  # noqa: F811
    _, app, _, _ = env
    assert TestClient(app).get("/api/market/forecast").status_code in (401, 403)


def test_levels_for_a_stock_come_from_its_bars_since_its_last_split(env):  # noqa: F811
    import math

    from tests.integration.conftest import bar

    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    iid = conn.execute(
        "SELECT min(instrument_id) FROM instrument WHERE asset_class='equity' AND instrument_id NOT IN (SELECT instrument_id FROM bar_1d)"
    ).fetchone()[0]
    sym = conn.execute("SELECT symbol FROM instrument WHERE instrument_id=%s", (iid,)).fetchone()[0]
    for k in range(120):  # a stock bouncing between about 100 and 110
        bar(
            conn,
            iid,
            TODAY - timedelta(days=119 - k),
            round(105 + 5 * math.sin(2 * math.pi * k / 20), 2),
            1000 + k,
            500,
        )
    got = c.get("/api/market/levels", params={"symbol": sym}).json()
    assert got["symbol"] == sym and got["enough_history"] and got["as_of"] == "2026-11-11"
    assert got["supports"] and got["resistances"] and got["status"]["state"]
    assert (
        len(got["profile"]["bins"]) == 24
        and sum(b["count"] for b in got["returns"]["bins"]) == 119
        and len(got["series"]) == 120
    )
    assert c.get("/api/market/levels", params={"symbol": "NOPE"}).status_code == 404


def test_news_gives_recent_headlines_the_mood_by_day_and_the_stocks_named_most(env):  # noqa: F811
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    assert c.get("/api/market/news").json() == {"items": [], "mood": [], "stocks": []}
    now = clock.now()
    for k, (title, sent, syms) in enumerate(
        [
            ("Sensex surges", 0.6, ["TCS"]),
            ("Nifty slides", -0.5, ["TCS", "ITC"]),
            ("Board meeting", None, []),
        ]
    ):
        conn.execute(
            "INSERT INTO news_item (item_id, source, title, url, published_at, first_seen_at, sentiment, hits, symbols) VALUES (%s,'feed',%s,%s,%s,%s,%s,1,%s)",
            (f"i{k}", title, f"https://ex.com/{k}", now - timedelta(hours=k), now, sent, syms),
        )
    got = c.get("/api/market/news").json()
    assert [i["title"] for i in got["items"]] == [
        "Sensex surges",
        "Nifty slides",
        "Board meeting",
    ] and got["items"][2]["sentiment"] is None
    assert (
        sum(m["n"] for m in got["mood"]) == 2
        and sum(m["positive"] for m in got["mood"]) == 1
        and sum(m["negative"] for m in got["mood"]) == 1
    )  # the unscored one is not counted
    assert got["stocks"][0] == {"symbol": "TCS", "mentions": 2, "avg": pytest.approx(0.05)}
    conn.execute(
        "INSERT INTO news_item (item_id, source, title, url, published_at, first_seen_at, sentiment, hits, symbols) VALUES ('old','feed','TCS a month ago','https://ex.com/old',%s,%s,0.2,1,%s)",
        (now - timedelta(days=45), now, ["TCS"]),
    )
    only = c.get("/api/market/news", params={"symbol": " tcs "}).json()
    assert [i["title"] for i in only["items"]] == [
        "Sensex surges",
        "Nifty slides",
    ]  # headlines naming it, newest first; the 45-day-old one is out
    assert only["mood"] == [] and only["stocks"] == []
    assert c.get("/api/market/news", params={"symbol": "NOPE"}).json()["items"] == []


def test_score_for_a_stock_gives_today_its_parts_and_the_history(env):  # noqa: F811
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    iid, sym = conn.execute(
        "SELECT instrument_id, symbol FROM instrument WHERE asset_class='equity' ORDER BY instrument_id LIMIT 1"
    ).fetchone()
    assert (
        c.get("/api/market/score", params={"symbol": sym}).json()["scored"] is False
    )  # not in the snapshot: no score, nothing invented
    conn.execute(
        "INSERT INTO screener_snapshot (instrument_id, as_of, row, built_at) VALUES (%s, %s, %s, now())",
        (
            iid,
            TODAY,
            Jsonb(
                {
                    "as_of": "2026-11-11",
                    "score": 71.4,
                    "score_trend": 80.0,
                    "score_participation": 55.5,
                    "score_quality": 60.0,
                    "setup": "Accumulation",
                    "score_why": "Rising over 1 month",
                }
            ),
        ),
    )
    for k in range(3):
        conn.execute(
            "INSERT INTO stock_score_history (day, instrument_id, score, trend) VALUES (%s,%s,%s,%s)",
            (TODAY - timedelta(days=7 * (2 - k)), iid, 60 + k, 50.0),
        )
    got = c.get("/api/market/score", params={"symbol": sym}).json()
    assert (
        got["scored"]
        and got["score"] == 71.4
        and got["components"]
        == {"trend": 80.0, "participation": 55.5, "smart_money": None, "quality": 60.0}
    )
    assert (
        got["setup"] == "Accumulation"
        and got["why"] == "Rising over 1 month"
        and [h["score"] for h in got["history"]] == [60, 61, 62]
    )
    assert c.get("/api/market/score", params={"symbol": "NOPE"}).status_code == 404


def test_rise_odds_for_a_stock_are_its_walk_forward_history_and_the_newest_day_is_the_latest(env):  # noqa: F811
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    iid, sym = conn.execute(
        "SELECT instrument_id, symbol FROM instrument WHERE asset_class='equity' ORDER BY instrument_id LIMIT 1"
    ).fetchone()
    nothing = c.get("/api/market/rise-odds", params={"symbol": sym}).json()
    assert (
        nothing["scored"] is False
        and nothing["latest"] is None
        and nothing["history"] == []
        and nothing["horizon"] == 5
    )  # not scored: nothing invented
    conn.execute(
        "INSERT INTO rise_odds_model (version, horizon, train_end, trained_at, n_rows, features, payload, sha256) VALUES ('h5-2026-01-01', 5, '2026-01-01', now(), 1, %s, %s, 'x')",
        (["a"], b"x"),
    )
    for k in range(3):
        conn.execute(
            "INSERT INTO rise_odds (day, instrument_id, horizon, prob, pct, model_version) VALUES (%s,%s,5,%s,%s,'h5-2026-01-01')",
            (TODAY - timedelta(days=2 - k), iid, 0.5 + 0.01 * k, 90.0 + k),
        )
    got = c.get(
        "/api/market/rise-odds", params={"symbol": sym.lower()}
    ).json()  # the symbol is case-insensitive
    assert got["scored"] and got["symbol"] == sym and got["model_version"] == "h5-2026-01-01"
    assert [h["pct"] for h in got["history"]] == [90.0, 91.0, 92.0]  # oldest first
    assert got["latest"] == {"day": TODAY.isoformat(), "prob": 0.52, "pct": 92.0}
    assert c.get("/api/market/rise-odds", params={"symbol": "NOPE"}).status_code == 404
    own = c.get(
        "/api/market/rise-odds", params={"symbol": sym, "kind": "up"}
    ).json()  # the own-direction kind is kept apart: nothing stored for it yet
    assert own["kind"] == "up" and own["scored"] is False and got["kind"] == "rel"
    conn.execute(
        "INSERT INTO rise_odds_model (version, horizon, train_end, trained_at, n_rows, features, payload, sha256, kind) VALUES ('h5up-2026-01-01', 5, '2026-01-01', now(), 1, %s, %s, 'x', 'up')",
        (["a"], b"x"),
    )
    conn.execute(
        "INSERT INTO rise_odds (day, instrument_id, horizon, prob, pct, model_version, kind) VALUES (%s,%s,5,0.61,88,'h5up-2026-01-01','up')",
        (TODAY, iid),
    )
    own = c.get("/api/market/rise-odds", params={"symbol": sym, "kind": "up"}).json()
    assert (
        own["scored"]
        and own["latest"]["pct"] == 88.0
        and own["model_version"] == "h5up-2026-01-01"
        and len(own["history"]) == 1
    )
    assert [
        h["pct"] for h in c.get("/api/market/rise-odds", params={"symbol": sym}).json()["history"]
    ] == [90.0, 91.0, 92.0]  # the relative history is unchanged
    assert (
        c.get("/api/market/rise-odds", params={"symbol": sym, "kind": "sideways"}).status_code
        == 422
    )


def test_the_top_rise_odds_are_the_newest_days_best_stocks_with_a_capped_list(env):  # noqa: F811
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    assert c.get("/api/market/rise-odds/top").json() == {
        "day": None,
        "horizon": 5,
        "kind": "rel",
        "side": "top",
        "model_version": None,
        "items": [],
    }  # no scores yet
    ids = [
        r[0]
        for r in conn.execute(
            "SELECT instrument_id FROM instrument WHERE asset_class='equity' ORDER BY instrument_id"
        )
    ]
    conn.execute(
        "INSERT INTO rise_odds_model (version, horizon, train_end, trained_at, n_rows, features, payload, sha256) VALUES ('h5-2026-01-01', 5, '2026-01-01', now(), 1, %s, %s, 'x')",
        (["a"], b"x"),
    )
    for k, iid in enumerate(ids):
        conn.execute(
            "INSERT INTO rise_odds (day, instrument_id, horizon, prob, pct, model_version) VALUES (%s,%s,5,%s,%s,'h5-2026-01-01')",
            (TODAY, iid, 0.4 + 0.05 * k, 10.0 * k),
        )
        conn.execute(
            "INSERT INTO rise_odds (day, instrument_id, horizon, prob, pct, model_version) VALUES (%s,%s,5,0.99,99,'h5-2026-01-01')",
            (TODAY - timedelta(days=9), iid),
        )  # an older day: ignored
    got = c.get("/api/market/rise-odds/top", params={"limit": 1}).json()
    assert got["day"] == TODAY.isoformat() and got["model_version"] == "h5-2026-01-01"
    assert len(got["items"]) == 1 and got["items"][0]["prob"] == round(
        0.4 + 0.05 * (len(ids) - 1), 4
    )  # the highest chance of the newest day
    assert (
        got["items"][0]["instrument_id"] == ids[-1] and got["items"][0]["symbol"]
    )  # with the id the page links to
    assert (
        len(c.get("/api/market/rise-odds/top", params={"limit": 0}).json()["items"]) == 1
    )  # a silly limit is raised to 1, never an error
    low = c.get("/api/market/rise-odds/top", params={"limit": 1, "side": "bottom"}).json()
    assert (
        low["side"] == "bottom"
        and low["items"][0]["prob"] == 0.4
        and low["items"][0]["instrument_id"] == ids[0]
    )  # the lowest chance of the newest day
    assert c.get("/api/market/rise-odds/top", params={"side": "sideways"}).status_code == 422
    assert (
        c.get("/api/market/rise-odds/top", params={"kind": "up"}).json()["items"] == []
    )  # no own-direction scores yet: its list is its own
    assert c.get("/api/market/rise-odds/top", params={"kind": "nope"}).status_code == 422


def test_industries_count_breadth_inside_each_group_and_skip_stocks_with_no_sector(env):  # noqa: F811
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    assert c.get("/api/market/industries").json() == {"as_of": None, "industries": []}
    from algo.data.store.instruments import InstrumentRepo

    ids = [
        r[0]
        for r in conn.execute(
            "SELECT instrument_id FROM instrument WHERE asset_class='equity' ORDER BY instrument_id LIMIT 2"
        )
    ]
    ids.append(
        InstrumentRepo(conn).add_instrument(
            conn.execute("SELECT min(exchange_id) FROM exchange").fetchone()[0], "NOSECTOR"
        )
    )  # a listed stock that is not on the Nifty 500 list
    for iid, sector in ((ids[0], "IT"), (ids[1], "IT"), (ids[2], None)):
        if sector:
            conn.execute(
                "INSERT INTO instrument_sector (instrument_id, sector, effective_from, source_sha256, ingested_at) VALUES (%s,%s,%s,'x',now())",
                (iid, sector, date(2026, 1, 1)),
            )
    rows = [
        (
            ids[0],
            {
                "symbol": "A",
                "as_of": "2026-11-11",
                "price_vs_sma50": 3,
                "price_vs_sma200": 5,
                "chg_1d": 1.0,
                "chg_1m": 4.0,
                "score": 80.0,
            },
        ),
        (
            ids[1],
            {
                "symbol": "B",
                "as_of": "2026-11-11",
                "price_vs_sma50": -2,
                "price_vs_sma200": 5,
                "chg_1d": -1.0,
                "chg_1m": -6.0,
                "score": 40.0,
            },
        ),
        (
            ids[2],
            {
                "symbol": "C",
                "as_of": "2026-11-11",
                "price_vs_sma50": 9,
                "chg_1d": 2.0,
                "score": 99.0,
            },
        ),  # no sector: not counted
    ]
    for iid, r in rows:
        conn.execute(
            "INSERT INTO screener_snapshot (instrument_id, as_of, row, built_at) VALUES (%s,%s,%s,now())",
            (iid, TODAY, Jsonb(r)),
        )
    assert (
        c.get("/api/market/industries").json()["industries"][0]["live_change"] is None
    )  # no live quotes yet
    for iid, ltp, prev in (
        (ids[0], 102, 100),
        (ids[1], 97, 100),
        (ids[2], 500, 400),
    ):  # +2% and -3% in the group; the stock with no sector is not counted
        conn.execute(
            "INSERT INTO live_quote (instrument_id, ltp, prev_close, updated_at) VALUES (%s,%s,%s,%s)",
            (iid, ltp, prev, clock.now()),
        )
    live_it = c.get("/api/market/industries").json()["industries"][0]
    assert round(live_it["live_change"], 2) == -0.5 and (
        live_it["live_up"],
        live_it["live_down"],
    ) == (1, 1)
    got = c.get("/api/market/industries").json()
    (it,) = got["industries"]
    assert got["as_of"] == "2026-11-11" and it["name"] == "IT" and it["stocks"] == 2
    assert (
        it["above_50"] == 50.0
        and it["above_200"] == 100.0
        and it["up_today"] == 50.0
        and it["avg_score"] == 60.0
        and it["top"] == ["A", "B"]
        and it["scored"] == 2
    )


def test_watchlist_adds_lists_removes_and_stays_personal(env):  # noqa: F811
    conn, app, clock, _ = env
    iid, sym, name = conn.execute(
        "SELECT instrument_id, symbol, name FROM instrument WHERE asset_class='equity' AND delisted_on IS NULL ORDER BY instrument_id LIMIT 1"
    ).fetchone()
    _, c = trader(conn, app, clock)
    assert c.get("/api/market/watchlist").json() == {"items": []}
    assert c.post("/api/market/watchlist", json={"symbol": f" {sym.lower()} "}).json() == {
        "ok": True
    }
    assert c.post("/api/market/watchlist", json={"symbol": sym}).json() == {
        "ok": True
    }  # twice is still once
    item = c.get("/api/market/watchlist").json()["items"][0]
    assert (item["instrument_id"], item["symbol"], item["name"]) == (iid, sym, name)
    assert (
        item["added_at"].startswith("2026-") and item["added_price"] == "210"
    )  # no quote or bar existed when it was added
    conn.execute(
        "INSERT INTO live_quote (instrument_id, ltp, updated_at) VALUES (%s, 123.45, now())", (iid,)
    )
    c.delete(f"/api/market/watchlist/{iid}")
    assert c.post("/api/market/watchlist", json={"symbol": sym}).json() == {"ok": True}
    assert (
        c.get("/api/market/watchlist").json()["items"][0]["added_price"] == "123.45"
    )  # the live price at the moment of adding
    assert c.post("/api/market/watchlist", json={"symbol": "NOPE"}).status_code == 404
    _, other = trader(conn, app, clock, email="other@example.com")
    assert other.get("/api/market/watchlist").json() == {"items": []}
    assert c.delete(f"/api/market/watchlist/{iid}").json() == {"ok": True}
    assert c.get("/api/market/watchlist").json() == {"items": []}


def test_watchlist_is_capped(env):  # noqa: F811
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    for i in range(51):
        conn.execute(
            "INSERT INTO instrument (symbol, name, asset_class, exchange_id, quote_currency) SELECT %s,'x','equity',exchange_id,quote_currency FROM instrument WHERE asset_class='equity' LIMIT 1",
            (f"ZZ{i}",),
        )
    codes = [
        c.post("/api/market/watchlist", json={"symbol": f"ZZ{i}"}).status_code for i in range(51)
    ]
    assert codes[:50] == [200] * 50 and codes[50] == 400


def test_the_zone_uses_the_live_reading_when_there_is_one_caches_it_and_falls_back_when_it_fails(
    env, monkeypatch
):  # noqa: F811
    from algo.api import zone_routes
    from algo.market.breadth import Breadth
    from algo.market.live_zone import LiveZone

    conn, app, clock, _ = env
    put(conn, TODAY - timedelta(days=1), 50.0, "Neutral", "SIDEWAYS", {"breadth": 40.0})
    _, c = trader(conn, app, clock)
    calls = []
    b = Breadth(TODAY, 1500, 300, 1190, 10, 1400, 600, 1300, 650, 20, 30)

    def fake(_conn, today, history_days):
        calls.append(today)
        return LiveZone(
            today,
            b,
            31.5,
            "Fear",
            "BEAR",
            "STRESSED",
            {"breadth": 20.0, "momentum": 70.0},
            [(TODAY - timedelta(days=1), 50.0, "SIDEWAYS"), (TODAY, 31.5, "BEAR")],
            {"breadth": "20.0% of stocks above their 50-day average", "momentum": None},
        )

    monkeypatch.setattr(zone_routes.live_zone, "live_zone", fake)
    got = c.get("/api/market/zone").json()
    assert {d["key"]: d["reading"] for d in got["drivers"]}[
        "breadth"
    ] == "20.0% of stocks above their 50-day average"
    assert (
        got["latest"]["live"] is True
        and got["latest"]["label"] == "Fear"
        and got["latest"]["day"] == TODAY.isoformat()
    )
    assert (
        got["latest"]["advancers"] == 300
        and got["latest"]["as_of"] is not None
        and got["latest"]["pct_above_50"] == round(100 * 600 / 1400, 1)
    )
    assert [d["key"] for d in got["drivers"]] == ["momentum", "breadth"] and got["history"][-1] == {
        "day": TODAY.isoformat(),
        "fear_greed": 31.5,
        "trend": "BEAR",
    }
    c.get("/api/market/zone")
    assert len(calls) == 1  # cached inside the interval
    clock.advance(timedelta(seconds=45))
    c.get("/api/market/zone")
    assert len(calls) == 2  # and worked out again after it

    def broken(*_a):
        raise RuntimeError("feed down")

    clock.advance(timedelta(seconds=45))
    monkeypatch.setattr(zone_routes.live_zone, "live_zone", broken)
    got = c.get("/api/market/zone").json()
    assert (
        got["latest"]["live"] is False and got["latest"]["fear_greed"] == 50.0
    )  # the snapshot stays when the live reading fails


def test_index_members_match_the_official_list_to_our_stocks_by_isin_and_say_when_there_is_none(
    env, tmp_path
):  # noqa: F811
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    from algo.data.store.instruments import InstrumentRepo

    repo, ex = (
        InstrumentRepo(conn),
        conn.execute("SELECT min(exchange_id) FROM exchange").fetchone()[0],
    )
    first, second = (
        (repo.add_instrument(ex, sym, isin=isin), sym, isin)
        for sym, isin in (("INFYX", "INE009A01021"), ("TCSX", "INE467B01029"))
    )
    folder = tmp_path / "raw/niftyindices/niftyit_list/dt=2026-11-17"
    folder.mkdir(parents=True)
    (folder / "v0001.bin").write_bytes(
        (
            "Company Name,Industry,Symbol,Series,ISIN Code\n"
            f"One,Information Technology,{first[1]},EQ,{first[2]}\n"
            f"Two,Information Technology,{second[1]},EQ,{second[2]}\n"
            "Gone Ltd.,Information Technology,GONE,EQ,INE000000000\n"
        ).encode()
    )
    app.state.lake = tmp_path
    got = c.get("/api/market/index-members", params={"symbol": "NIFTY IT"}).json()
    assert (got["kind"], got["symbol"], got["name"], got["as_of"], got["unmatched"]) == (
        "index",
        "NIFTY IT",
        "IT",
        "2026-11-17",
        1,
    )
    assert [m["instrument_id"] for m in got["members"]] == [first[0], second[0]] and got["members"][
        0
    ]["industry"] == "Information Technology"
    assert c.get("/api/market/index-members", params={"symbol": "SENSEX"}).status_code == 404
    assert c.get("/api/market/index-members").status_code == 400
    assert (
        c.get(
            "/api/market/index-members", params={"symbol": "NIFTY IT", "industry": "IT"}
        ).status_code
        == 400
    )
    assert (
        c.get("/api/market/index-members", params={"industry": "No such industry"}).status_code
        == 404
    )
    conn.execute(
        "INSERT INTO instrument_sector (instrument_id, sector, effective_from, source_sha256, ingested_at) VALUES (%s,'IT',%s,'x',now())",
        (first[0], date(2026, 1, 1)),
    )
    ind = c.get("/api/market/index-members", params={"industry": "IT"}).json()
    assert (ind["kind"], ind["name"], [m["instrument_id"] for m in ind["members"]]) == (
        "industry",
        "IT",
        [first[0]],
    )


def test_notes_are_served_per_stock_cached_for_a_minute_and_need_good_ids(env, monkeypatch):
    from algo.api import zone_routes
    from algo.market.notes import Note

    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    calls = []

    def fake(_conn, ids, now):
        calls.append(list(ids))
        return {ids[0]: [Note("breakout", "good", "Breakout", 1, "Closed above resistance")]}

    monkeypatch.setattr(zone_routes.stock_notes, "notes_for", fake)
    got = c.get("/api/market/notes", params={"ids": "7,3,3"}).json()
    assert got["notes"] == {
        "3": [
            {
                "kind": "breakout",
                "tone": "good",
                "text": "Breakout",
                "rank": 1,
                "detail": "Closed above resistance",
            }
        ]
    } and calls == [[3, 7]]
    c.get("/api/market/notes", params={"ids": "3,7"})
    assert len(calls) == 1  # the same list inside the minute is not worked out again
    clock.advance(timedelta(seconds=70))
    c.get("/api/market/notes", params={"ids": "3,7"})
    assert len(calls) == 2
    assert c.get("/api/market/notes", params={"ids": "x"}).status_code == 400
    assert TestClient(app).get("/api/market/notes", params={"ids": "1"}).status_code == 401


def test_each_headline_carries_one_reading_laya_where_it_has_scored_it_and_the_mood_uses_it(env):
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    now = clock.now()
    for k, (title, words, laya, lc) in enumerate(
        [
            ("Both agree", 0.6, 0.8, 0.9),
            ("Laya differs", 0.6, -0.7, 0.8),
            ("Words only", -0.5, None, None),
            ("Unread", None, None, None),
        ]
    ):
        conn.execute(
            "INSERT INTO news_item (item_id, source, title, summary, url, published_at, first_seen_at, sentiment, laya_sentiment, laya_confidence, hits, symbols) VALUES (%s,'feed',%s,'',%s,%s,%s,%s,%s,%s,1,%s)",
            (
                f"r{k}",
                title,
                f"https://ex.com/r{k}",
                now - timedelta(hours=k),
                now,
                words,
                laya,
                lc,
                ["TCS"],
            ),
        )
    got = c.get("/api/market/news").json()
    by = {i["title"]: i for i in got["items"]}
    assert (by["Both agree"]["reading"], by["Both agree"]["reading_model"]) == ("positive", "laya")
    assert (
        by["Laya differs"]["reading"],
        by["Laya differs"]["sentiment"],
        by["Laya differs"]["laya"],
    ) == ("negative", 0.6, -0.7)  # the keyword value is kept, but not shown
    assert (by["Words only"]["reading"], by["Words only"]["reading_model"]) == ("negative", "words")
    assert (by["Unread"]["reading"], by["Unread"]["reading_model"]) == (None, None)
    assert (
        sum(m["n"] for m in got["mood"]) == 3
        and sum(m["positive"] for m in got["mood"]) == 1
        and sum(m["negative"] for m in got["mood"]) == 2
    )  # the unread one is not counted
    assert got["stocks"][0]["symbol"] == "TCS" and got["stocks"][0]["mentions"] == 3


def test_performance_gives_nifty_for_the_history_days_and_the_return_after_each_zone(env):  # noqa: F811
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    for i in range(8):
        d = TODAY - timedelta(days=7 - i)
        put(conn, d, 20.0 if i < 4 else 80.0, "x", "BULL")
        conn.execute(
            "INSERT INTO index_bar_1d (exchange, symbol, trade_date, open, high, low, close, token, ingested_at) VALUES ('NSE','NIFTY 50',%s,1,1,1,%s,1,%s)",
            (d, 100 + i, NOW),
        )
    got = c.get("/api/market/zone/performance").json()
    assert [n["close"] for n in got["nifty"]] == [100 + i for i in range(8)]
    rows = {r["zone"]: r for r in got["zones"]}
    assert (
        rows["Extreme fear"]["days"] == 4
        and rows["Extreme greed"]["days"] == 4
        and rows["Fear"]["days"] == 0
    )
    assert rows["Extreme fear"]["forward"][0]["avg_pct"] > 0


def test_forecast_carries_what_the_market_and_sectors_are_doing_today_from_the_live_quotes(env):  # noqa: F811
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    log(conn, TODAY - timedelta(days=1), "MARKET", 1, 0.58, True)
    assert c.get("/api/market/forecast").json()["today"] == {
        "market_change_pct": None,
        "as_of": None,
        "sectors": {},
    }  # the feed is off
    for token, symbol, ltp, prev in ((1, "NIFTY 500", 101.0, 100.0), (2, "NIFTY IT", 49.0, 50.0)):
        conn.execute(
            "INSERT INTO index_live_quote (token, exchange, symbol, ltp, prev_close, updated_at) VALUES (%s,'NSE',%s,%s,%s,%s)",
            (token, symbol, ltp, prev, clock.now()),
        )
    today = c.get("/api/market/forecast").json()["today"]
    assert round(today["market_change_pct"], 2) == 1.0 and today["as_of"] is not None
    assert {k: round(v, 2) for k, v in today["sectors"].items()} == {"IT": -2.0}


def test_forecast_carries_the_overnight_us_moves_and_gift_nifty_with_how_such_mornings_ended(env):  # noqa: F811
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    mon, tue = (
        date(2026, 11, 9),
        date(2026, 11, 10),
    )  # as_of is Tuesday: the forecast is for Wednesday the 11th
    log(conn, tue, "MARKET", 1, 0.58, True)
    for d, close in ((mon, 1000.0), (tue, 1010.0), (date(2026, 11, 11), 1030.0)):
        for symbol, px in (("NIFTY 50", close), ("NIFTY 500", close)):
            conn.execute(
                "INSERT INTO index_bar_1d (exchange, symbol, trade_date, open, high, low, close, token, ingested_at) VALUES ('NSE',%s,%s,1,1,1,%s,1,%s) ON CONFLICT DO NOTHING",
                (symbol, d, px, NOW),
            )
    for symbol, rows in (
        (
            "SP500",
            ((tue - timedelta(days=1), 100.0), (tue, 102.0)),
        ),  # +2.0% in the last session before Wednesday
        ("NASDAQ", ((tue - timedelta(days=1), 100.0), (tue, 99.0))),
        (
            "GIFT0845",
            ((date(2026, 11, 11), 1020.1), (tue, 1011.0)),
        ),  # Wednesday: +1.0% against Tuesday's 1010 close; Tuesday: +1.1% against Monday's 1000
    ):
        for d, px in rows:
            conn.execute(
                "INSERT INTO global_daily (symbol, day, close, source, ingested_at) VALUES (%s,%s,%s,'test',%s)",
                (symbol, d, px, NOW),
            )
    o = c.get("/api/market/forecast").json()["overnight"]
    assert (
        o["for_day"] == "2026-11-11"
        and round(o["sp"], 2) == 2.0
        and round(o["nq"], 2) == -1.0
        and o["vix"] is None
    )
    assert round(o["gift_gap_pct"], 2) == 1.0
    up = {r["label"]: r for r in o["gift_history"]}["Up more than 0.3%"]
    assert (
        up["days"] == 2 and up["up_pct"] == 100.0
    )  # both mornings GIFT indicated over +0.3% and the Nifty 500 closed higher


def test_range_forecast_with_nothing_made_is_an_empty_answer(env):  # noqa: F811
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    assert c.get("/api/market/range-forecast").json() == {
        "latest": None,
        "five_session_avg": None,
        "yesterday_range": None,
        "record": [],
        "resolved": 0,
        "needed": 500,
    }


def test_range_forecast_gives_the_latest_forecast_beside_the_baselines_and_the_resolved_record(env):  # noqa: F811
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    days = [
        TODAY - timedelta(days=k) for k in (6, 5, 4, 3, 2, 1)
    ]  # Tue 3 Nov .. Mon 9 Nov... six sessions before TODAY
    for i, d in enumerate(days):
        conn.execute(
            "INSERT INTO index_bar_1d (exchange, symbol, trade_date, open, high, low, close, token, ingested_at) VALUES ('NSE','NIFTY 500',%s,1000,%s,%s,1000,1,%s)",
            (d, 1000 + 5 * (i + 1), 1000 - 5 * (i + 1), NOW),
        )  # ranges 1.0, 2.0, 3.0, 4.0, 5.0, 6.0 percent of the open
    conn.execute(
        "INSERT INTO range_forecast_log (as_of, model_version, made_at, forecast_range, features, train_through, n_train, target_day, actual_range, resolved_on) VALUES (%s,'range-ridge-v1',%s,1.2,'{}',%s,600,%s,1.4,%s)",
        (days[0], NOW, days[0], days[1], days[1]),
    )
    conn.execute(
        "INSERT INTO range_forecast_log (as_of, model_version, made_at, forecast_range, features, train_through, n_train) VALUES (%s,'range-ridge-v1',%s,3.5,'{}',%s,600)",
        (days[-1], NOW, days[-1]),
    )
    got = c.get("/api/market/range-forecast").json()
    assert (
        got["latest"]["as_of"] == days[-1].isoformat()
        and got["latest"]["forecast_range"] == 3.5
        and got["latest"]["actual_range"] is None
        and got["latest"]["version"] == "range-ridge-v1"
    )
    assert got["latest"]["for_day"] == TODAY.isoformat()  # the next weekday after the last session
    assert got["five_session_avg"] == pytest.approx(4.0) and got[
        "yesterday_range"
    ] == pytest.approx(6.0)  # sessions 2..6: 2,3,4,5,6 average 4
    assert got["record"] == [
        {
            "target_day": days[1].isoformat(),
            "forecast": pytest.approx(1.2),
            "actual": pytest.approx(1.4),
        }
    ]
    assert got["resolved"] == 1 and got["needed"] == 500


def test_index_bars_come_back_in_the_stock_chart_shape_and_unknown_ones_are_refused(env):  # noqa: F811
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    for k in range(3):
        conn.execute(
            "INSERT INTO index_bar_1d (exchange, symbol, trade_date, open, high, low, close, token, ingested_at) VALUES ('NSE','NIFTY 50',%s,100,110,90,105,1,%s)",
            (TODAY - timedelta(days=2 - k), NOW),
        )
    got = c.get("/api/market/index/bars", params={"symbol": "NIFTY 50", "timeframe": "1d"}).json()
    assert (
        got["symbol"] == "NIFTY 50"
        and got["exchange"] == "NSE"
        and got["timeframe"] == "1d"
        and len(got["bars"]) == 3
    )
    assert (
        got["bars"][0]["volume"] == "0"
        and got["bars"][0]["factor"] == "1"
        and "time" not in got["bars"][0]
    )
    assert (
        got["first"] == (TODAY - timedelta(days=2)).isoformat()
        and got["last"] == TODAY.isoformat()
        and got["intraday_first"] is None
    )
    assert c.get("/api/market/index/bars", params={"symbol": "NOT AN INDEX"}).status_code == 404
    assert (
        c.get(
            "/api/market/index/bars", params={"symbol": "NIFTY 50", "timeframe": "7m"}
        ).status_code
        == 422
    )


def _context_world(conn):
    """Two IT stocks (A rising fast, B slowly) and a flat one with no sector, 260 weekdays to TODAY, and a Nifty 50 that rises every day."""
    from algo.data.store.instruments import InstrumentRepo

    ids = [
        r[0]
        for r in conn.execute(
            "SELECT instrument_id FROM instrument WHERE asset_class='equity' ORDER BY instrument_id LIMIT 2"
        )
    ]
    ids.append(
        InstrumentRepo(conn).add_instrument(
            conn.execute("SELECT min(exchange_id) FROM exchange").fetchone()[0], "FLATCO"
        )
    )
    conn.execute("DELETE FROM bar_1d WHERE instrument_id = ANY(%s)", (ids,))
    conn.execute("DELETE FROM index_bar_1d WHERE symbol='NIFTY 50'")
    days, d = [], TODAY
    while len(days) < 260:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    days.reverse()
    for iid, step in zip(ids, (1.0, 0.3, 0.0), strict=True):
        for i, day in enumerate(days):
            p = 100 + step * i
            conn.execute(
                "INSERT INTO bar_1d (instrument_id, ts, open, high, low, close, volume, series, source, dataset_version, ingested_at) VALUES (%s, %s::date + time '03:45', %s, %s, %s, %s, 1000, 'EQ', 'nse', 1, now())",
                (iid, day, p, p + 0.5, p - 0.5, p),
            )
    for i, day in enumerate(days):
        conn.execute(
            "INSERT INTO index_bar_1d (exchange, symbol, trade_date, open, high, low, close, token, ingested_at) VALUES ('NSE','NIFTY 50',%s,1,1,1,%s,1,now())",
            (day, 1000 + 5 * i),
        )
    for iid in ids[:2]:
        conn.execute(
            "INSERT INTO instrument_sector (instrument_id, sector, effective_from, source_sha256, ingested_at) VALUES (%s,'IT','2026-01-01','x',now())",
            (iid,),
        )
    return ids


def test_stock_context_describes_regime_sector_strength_and_momentum_without_a_direction(env):  # noqa: F811
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    ids = _context_world(conn)
    sym = conn.execute(
        "SELECT symbol FROM instrument WHERE instrument_id=%s", (ids[0],)
    ).fetchone()[0]
    got = c.get("/api/market/context", params={"symbol": sym.lower()}).json()
    assert got["symbol"] == sym and got["as_of"] == TODAY.isoformat() and got["adjusted"] is False
    assert got["regime"]["label"] == "uptrend" and got["regime"]["as_of"] == TODAY.isoformat()
    sector = got["sector"]
    assert (
        sector["name"] == "IT"
        and sector["n"] == 2
        and sector["window"] == 20
        and sector["verdict"] == "outperforming"
        and sector["sector_ret"] > sector["market_ret"]
    )
    assert (
        got["strength"]["ret_60d"] > got["strength"]["nifty_ret_60d"] > 0
        and got["strength"]["sector_ret_60d"] > 0
    )
    m = got["momentum"]
    assert m["ema_trend"] == "above" and m["rsi"] > 70 and m["adx_label"] == "strong trend"
    b = got[
        "breakout"
    ]  # a steadily rising stock: over its 20-day and 52-week highs, yesterday too, and above its EMA20
    assert (
        b["above_20d_high"] is True
        and b["breakout"] == "already above"
        and b["new_52w_high"] is True
        and b["extension_atr"] > 0
        and b["high_20d"] <= b["high_52w"]
    )
    assert not {"buy", "sell", "signal", "prob", "probability"} & set(
        got
    )  # described, never predicted
    assert c.get("/api/market/context", params={"symbol": "NOPE"}).status_code == 404


def test_stock_context_withholds_a_stocks_own_numbers_after_a_recent_split_and_copes_with_no_bars(
    env,
):  # noqa: F811
    conn, app, clock, _ = env
    _, c = trader(conn, app, clock)
    ids = _context_world(conn)
    sym = conn.execute(
        "SELECT symbol FROM instrument WHERE instrument_id=%s", (ids[0],)
    ).fetchone()[0]
    add_action(conn, ids[0], TODAY - timedelta(days=10), "split", num=2, den=1)
    got = c.get("/api/market/context", params={"symbol": sym}).json()
    assert (
        got["adjusted"] is True
        and got["momentum"] is None
        and got["strength"] is None
        and got["breakout"] is None
    )
    assert (
        got["regime"]["label"] == "uptrend" and got["sector"]["name"] == "IT"
    )  # the market's own picture stays
    conn.execute("DELETE FROM bar_1d WHERE instrument_id=%s", (ids[1],))
    empty = c.get(
        "/api/market/context",
        params={
            "symbol": conn.execute(
                "SELECT symbol FROM instrument WHERE instrument_id=%s", (ids[1],)
            ).fetchone()[0]
        },
    ).json()
    assert (
        empty["as_of"] is None
        and empty["regime"] is None
        and empty["sector"] is None
        and empty["momentum"] is None
        and empty["breakout"] is None
    )
