# ruff: noqa: E501
"""Rise odds against a real database: a stored model is read back only while its hash matches, the nightly run trains once and scores the newest day, catches up days it missed with the model
allowed for each, retrains an old model, and the backfill never scores a day with a model trained on data from after it."""

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.market import rise_odds as ro

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 14, 14, 0, tzinfo=UTC)
LEAF = 30  # small leaves: the test data is small


def seed(conn, first: date, n_days: int, n_stocks: int = 24, seed_: int = 3, thin: int = 0):
    """Random-walk bars for `n_stocks` stocks on weekdays from `first`; the last `thin` stocks trade almost nothing. Returns the list of instrument ids and the days."""
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    ids = [repo.add_instrument(x, f"S{i:02d}") for i in range(n_stocks)]
    rng = np.random.default_rng(seed_)
    days = list(pd.bdate_range(first, periods=n_days).date)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, size=(n_days, n_stocks)), axis=0))
    rows = []
    for j, iid in enumerate(ids):
        for i, d in enumerate(days):
            c = float(close[i, j])
            vol = 50 if j >= n_stocks - thin else 2_000_000
            rows.append((iid, d, c, c * 1.01, c * 0.99, c, vol, vol * (0.4 + 0.3 * rng.random())))
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO bar_1d (instrument_id, ts, open, high, low, close, volume, series, delivery_qty, source, dataset_version, ingested_at)"
            " VALUES (%s, %s::date + time '03:45', %s, %s, %s, %s, %s, 'EQ', %s, 'nse', 1, now())",
            [
                (i, d, c, h, lo, c, v, dq)
                for i, d, c, h, lo, c, v, dq in [
                    (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]) for r in rows
                ]
            ],
        )
    return ids, days


def test_a_stored_model_is_read_back_only_while_its_hash_and_features_match(conn):
    migrate(conn)
    v = ro.save_model(conn, {"a": 1}, date(2026, 1, 1), 1000, NOW)
    assert v == "h5-2026-01-01"
    assert ro.load_model(conn, v) == {"a": 1}
    assert (
        ro.save_model(conn, {"a": 2}, date(2026, 1, 1), 5, NOW) == v
    )  # a model for that day already exists: kept as it was
    assert ro.load_model(conn, v) == {"a": 1}
    conn.execute("UPDATE rise_odds_model SET payload=%s", (b"tampered",))
    with pytest.raises(ValueError, match="hash"):
        ro.load_model(conn, v)
    conn.execute(
        "UPDATE rise_odds_model SET features=%s, payload=%s, sha256=encode(sha256(%s), 'hex')",
        (["x"], b"p", b"p"),
    )
    with pytest.raises(ValueError, match="other features"):
        ro.load_model(conn, v)
    with pytest.raises(KeyError):
        ro.load_model(conn, "h5-1999-01-01")


def test_the_newest_model_allowed_to_score_a_day_is_the_latest_one_trained_on_or_before_it(conn):
    migrate(conn)
    assert ro.model_for(conn, date(2026, 6, 1)) is None
    for d in (date(2026, 1, 1), date(2026, 4, 1)):
        ro.save_model(conn, {}, d, 10, NOW)
    assert ro.model_for(conn, date(2025, 12, 31)) is None  # before the first: it would look ahead
    assert ro.model_for(conn, date(2026, 3, 31)) == ("h5-2026-01-01", date(2026, 1, 1))
    assert ro.model_for(conn, date(2026, 4, 1)) == ("h5-2026-04-01", date(2026, 4, 1))
    assert ro.model_for(conn, date(2026, 4, 1), horizon=10) is None


def test_with_no_bars_or_too_few_it_says_so_and_stores_nothing(conn):
    migrate(conn)
    assert ro.nightly(conn, NOW, LEAF).status == "no_bars"
    seed(conn, date(2026, 10, 1), 20)
    assert ro.nightly(conn, NOW, LEAF).status == "too_little_history"
    assert conn.execute("SELECT count(*) FROM rise_odds").fetchone()[0] == 0


def test_the_nightly_run_trains_once_per_kind_scores_the_liquid_stocks_of_the_newest_day_and_is_then_up_to_date(
    conn,
):
    ids, days = seed(conn, date(2025, 6, 2), 360, thin=3)
    out = ro.nightly(conn, NOW, LEAF)
    assert out.status == "scored", out
    assert conn.execute(
        "SELECT kind, count(*) FROM rise_odds_model GROUP BY kind ORDER BY kind"
    ).fetchall() == [("rel", 1), ("up", 1)]
    assert conn.execute("SELECT features FROM rise_odds_model WHERE kind='up'").fetchone()[
        0
    ] == list(ro.OWN_FEATURES)
    for kind, version in (
        ("rel", f"h5-{days[-1].isoformat()}"),
        ("up", f"h5up-{days[-1].isoformat()}"),
    ):
        rows = conn.execute(
            "SELECT day, instrument_id, prob, pct, model_version FROM rise_odds WHERE kind=%s",
            (kind,),
        ).fetchall()
        assert {r[0] for r in rows} == {
            days[-1]
        }  # the first night scores only the newest day: earlier days need the walk-forward backfill
        assert len(rows) == 21 and {r[1] for r in rows} == set(
            ids[:21]
        )  # the 3 thinly traded stocks are not scored
        assert all(0 <= r[2] <= 1 and 0 < r[3] <= 100 for r in rows) and max(
            r[3] for r in rows
        ) == pytest.approx(100)
        assert {r[4] for r in rows} == {version}
    assert ro.nightly(conn, NOW, LEAF).status == "up_to_date"
    assert conn.execute("SELECT count(*) FROM rise_odds_model").fetchone()[0] == 2


def test_days_missed_are_caught_up_each_with_the_newest_model_allowed_for_that_day(conn):
    ids, days = seed(conn, date(2025, 6, 2), 360)
    early = days[-8]  # a model trained 8 sessions ago exists already; the scores stop at days[-9]
    assert ro.train_model(conn, early, NOW, min_leaf=LEAF) == f"h5-{early.isoformat()}"
    conn.execute(
        "INSERT INTO rise_odds (day, instrument_id, horizon, prob, pct, model_version) VALUES (%s,%s,5,0.5,50,%s)",
        (days[-9], ids[0], f"h5-{early.isoformat()}"),
    )
    out = ro.nightly(conn, NOW, LEAF)
    assert out.status == "scored", out
    got = conn.execute(
        "SELECT day, count(*), min(model_version) FROM rise_odds WHERE kind='rel' AND day > %s GROUP BY day ORDER BY day",
        (days[-9],),
    ).fetchall()
    assert [g[0] for g in got] == days[-8:]
    for day, n, version in got:
        assert (
            date.fromisoformat(version.split("-", 1)[1]) <= day
        )  # never a model trained after the day it scores
        assert n > 15


def test_a_model_older_than_six_weeks_is_replaced_and_a_fresh_one_is_kept(conn):
    _, days = seed(conn, date(2025, 6, 2), 360)
    old = days[-1] - timedelta(days=ro.RETRAIN_DAYS + 5)
    ro.train_model(conn, old, NOW, min_leaf=LEAF)
    assert ro.nightly(conn, NOW, LEAF).status == "scored"
    assert [
        r[0]
        for r in conn.execute(
            "SELECT train_end FROM rise_odds_model WHERE kind='rel' ORDER BY train_end"
        )
    ] == [old, days[-1]]
    conn.execute("TRUNCATE rise_odds")
    ro.nightly(conn, NOW, LEAF)  # the newest models are from today: no new ones
    assert conn.execute("SELECT count(*) FROM rise_odds_model WHERE kind='rel'").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM rise_odds_model WHERE kind='up'").fetchone()[0] == 1


def test_the_backfill_scores_each_year_with_a_model_trained_only_on_the_data_before_it(conn):
    _, days = seed(conn, date(2025, 1, 1), 480)  # 2025-01-01 .. late 2026
    assert ro.backfill(conn, date(2026, 1, 1), NOW, min_leaf=LEAF) > 0
    rows = conn.execute("SELECT day, model_version FROM rise_odds").fetchall()
    assert (
        rows and min(r[0] for r in rows) >= date(2026, 1, 1) and max(r[0] for r in rows) == days[-1]
    )
    for day, version in rows:
        assert (
            date.fromisoformat(version.split("-", 1)[1]) <= day
        )  # walk-forward: a model scores only from its train_end on
    assert {r[1] for r in rows} == {"h5-2026-01-01", "h5up-2026-01-01"}  # one model per kind
    assert conn.execute("SELECT count(*) FROM rise_odds_model").fetchone()[0] == 2
    n_before = conn.execute("SELECT count(*) FROM rise_odds").fetchone()[0]
    assert (
        ro.backfill(conn, date(2026, 1, 1), NOW, until=date(2026, 6, 30), min_leaf=LEAF) > 0
    )  # run again over a shorter span: scores replaced, not doubled
    assert conn.execute("SELECT count(*) FROM rise_odds").fetchone()[0] == n_before


def test_a_backfill_with_too_little_history_before_the_year_stores_nothing(conn):
    seed(conn, date(2026, 6, 1), 120)
    assert (
        ro.backfill(conn, date(2026, 1, 1), NOW, min_leaf=LEAF) == 0
    )  # nothing before 1 January 2026 to train on


def test_a_backfill_with_no_bars_at_all_stores_nothing(conn):
    migrate(conn)
    assert ro.backfill(conn, date(2026, 1, 1), NOW, min_leaf=LEAF) == 0


def test_a_backfill_can_be_limited_to_one_kind(conn):
    seed(conn, date(2025, 1, 1), 480)
    assert ro.backfill(conn, date(2026, 1, 1), NOW, min_leaf=LEAF, kinds=("up",)) > 0
    assert {r[0] for r in conn.execute("SELECT DISTINCT kind FROM rise_odds")} == {"up"}
    assert [r[0] for r in conn.execute("SELECT version FROM rise_odds_model")] == [
        "h5up-2026-01-01"
    ]
