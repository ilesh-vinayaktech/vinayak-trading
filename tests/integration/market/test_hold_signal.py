# ruff: noqa: E501
"""The hold signal against a real database: a stored model is read back only while its hash and features match, the universe is the liquid equity stocks of the development period, the nightly run trains each year's
model once (on data that ended two years before the year), scores every day with it, carries each stock's held / flat state forward, catches up newly loaded days and never scores a day twice."""

from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest

from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.market import hold_signal as hs

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 14, 14, 0, tzinfo=UTC)
LEAF = 20  # small leaves: the test data is small
KW = {
    "score_from": date(2020, 1, 1),
    "universe_end": date(2019, 12, 31),
    "min_bars": 300,
    "min_turnover_cr": 0.001,
    "min_stocks": 20,
    "min_leaf": LEAF,
}
INSERT_KITE = "INSERT INTO bar_1d (instrument_id, ts, open, high, low, close, volume, series, source, dataset_version, ingested_at) VALUES (%s, %s::date + time '03:45', %s, %s, %s, %s, %s, NULL, 'kite', 1, now())"


def seed(conn, first: str, n_days: int, n_stocks: int = 30, thin: int = 2, seed_: int = 3):
    """Random-walk Kite bars for `n_stocks` equity stocks on weekdays from `first`; the last `thin` trade almost nothing. Each stock also has one NSE EQ bar (the universe is equity stocks). Returns (ids, days)."""
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    ids = [repo.add_instrument(x, f"H{i:02d}") for i in range(n_stocks)]
    rng = np.random.default_rng(seed_)
    days = list(pd.bdate_range(first, periods=n_days).date)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.02, size=(n_days, n_stocks)), axis=0))
    rows = []
    for j, iid in enumerate(ids):
        for i, d in enumerate(days):
            c = float(close[i, j])
            o = c * (1 + float(rng.normal(0, 0.004)))
            vol = 5 if j >= n_stocks - thin else 2_000_000
            rows.append((iid, d, o, max(o, c) * 1.005, min(o, c) * 0.995, c, vol))
    with conn.cursor() as cur:
        cur.executemany(INSERT_KITE, rows)
        cur.executemany(
            "INSERT INTO bar_1d (instrument_id, ts, open, high, low, close, volume, series, source, dataset_version, ingested_at) VALUES (%s, %s::date + time '03:45', 1, 1, 1, 1, 1, 'EQ', 'nse', 1, now())",
            [(iid, days[-1]) for iid in ids],
        )
    return ids, days


def test_a_stored_model_is_read_back_only_while_its_hash_and_features_match(conn):
    migrate(conn)
    v = hs.save_model(conn, {"x": 1}, date(2024, 12, 31), 5, NOW)
    assert v == "hold1-2024-12-31" and hs.load_model(conn, v) == {"x": 1}
    assert (
        hs.save_model(conn, {"y": 2}, date(2024, 12, 31), 5, NOW) == v
    )  # the same version is kept as it was
    assert hs.load_model(conn, v) == {"x": 1}
    conn.execute("UPDATE hold_signal_model SET sha256='bad' WHERE version=%s", (v,))
    with pytest.raises(ValueError, match="hash"):
        hs.load_model(conn, v)
    conn.execute(
        "UPDATE hold_signal_model SET sha256=encode(sha256(payload), 'hex'), features=%s WHERE version=%s",
        (["a"], v),
    )
    with pytest.raises(ValueError, match="other features"):
        hs.load_model(conn, v)
    with pytest.raises(KeyError):
        hs.load_model(conn, "hold1-1999-12-31")


def test_the_universe_is_the_liquid_equity_stocks_with_enough_bars(conn):
    ids, _ = seed(conn, "2017-01-02", 900, n_stocks=10, thin=2)
    assert hs.universe(conn, date(2019, 12, 31), 0.001, 300) == sorted(
        ids[:8]
    )  # the two thin stocks trade almost nothing
    assert hs.universe(conn, date(2017, 3, 1), 0.001, 300) == []  # too few bars by then
    conn.execute("DELETE FROM bar_1d WHERE source='nse'")
    assert (
        hs.universe(conn, date(2019, 12, 31), 0.001, 300) == []
    )  # no NSE equity bars: not an equity stock


def test_a_one_day_jump_makes_the_older_history_untrusted(conn):
    ids, days = seed(conn, "2017-01-02", 900, n_stocks=10, thin=0)
    cut = days[400]
    conn.execute(
        "UPDATE bar_1d SET close=close/10, open=open/10, high=high/10, low=low/10 WHERE source='kite' AND instrument_id=%s AND ts < %s::date + time '03:45'",
        (ids[0], cut),
    )
    bars = hs.load_bars(conn, ids, days[-1])
    assert bars[ids[0]].index.min() == pd.Timestamp(cut) and len(bars[ids[1]]) == 900


def test_the_nightly_run_trains_each_years_model_once_and_scores_every_day_with_the_right_one(conn):
    seed(conn, "2017-01-02", 1100)
    assert hs.nightly(conn, NOW, **KW).status == "scored"
    models = dict(conn.execute("SELECT version, train_end FROM hold_signal_model").fetchall())
    assert models
    rows = conn.execute("SELECT day, model_version FROM hold_signal").fetchall()
    assert rows
    for day, version in rows:
        assert models[version] == hs.train_end_for(
            day
        )  # never a model that saw the day's own year or the one before
        assert models[version] < date(day.year - 1, 1, 1)
    n_models = conn.execute("SELECT count(*) FROM hold_signal_model").fetchone()[0]
    assert hs.nightly(conn, NOW, **KW).status == "up_to_date"
    assert conn.execute("SELECT count(*) FROM hold_signal_model").fetchone()[0] == n_models


def test_actions_follow_the_thresholds_and_the_state_is_one_unbroken_walk(conn):
    seed(conn, "2017-01-02", 1100)
    hs.nightly(conn, NOW, **KW)
    df = pd.DataFrame(
        conn.execute(
            "SELECT day, instrument_id AS iid, rank_pct, action, in_position, entry_day FROM hold_signal ORDER BY instrument_id, day"
        ).fetchall(),
        columns=["day", "iid", "rank_pct", "action", "in_position", "entry_day"],
    )
    assert (
        set(df["action"]) <= {"BUY", "HOLD", "SELL", "NONE"}
        and (df["action"] == "BUY").any()
        and (df["action"] == "SELL").any()
    )
    assert df["rank_pct"].between(0, 100).all()
    for _, g in df.groupby("iid"):
        held = False
        for r in g.itertuples():
            if not held:
                assert r.action == ("BUY" if r.rank_pct >= hs.BUY_AT else "NONE")
            else:
                assert r.action == ("SELL" if r.rank_pct <= hs.SELL_AT else "HOLD")
            held = r.in_position
            assert (r.entry_day is not None) == r.in_position and (
                not r.in_position or r.entry_day <= r.day
            )
    assert (
        df.groupby("day")["rank_pct"].max() >= 95
    ).all()  # the best stock of every day ranks at the top (a tie in the chance gives an average rank a little under 100)


def test_new_days_are_scored_by_catching_up_and_the_state_carries_over(conn):
    seed(conn, "2017-01-02", 1100)
    last6 = conn.execute(
        "SELECT instrument_id, (ts AT TIME ZONE 'UTC')::date, open, high, low, close, volume FROM bar_1d WHERE source='kite' ORDER BY ts DESC, instrument_id LIMIT 6 * 30"
    ).fetchall()
    cut = min(r[1] for r in last6)
    conn.execute("DELETE FROM bar_1d WHERE source='kite' AND ts >= %s::date", (cut,))
    hs.nightly(conn, NOW, **KW)
    newest = conn.execute("SELECT max(day) FROM hold_signal").fetchone()[0]
    assert newest < cut
    before = {
        int(i): (bool(p), e)
        for i, p, e in conn.execute(
            "SELECT instrument_id, in_position, entry_day FROM hold_signal WHERE day=%s", (newest,)
        ).fetchall()
    }
    with conn.cursor() as cur:
        cur.executemany(INSERT_KITE, last6)  # the held-back days arrive
    out = hs.nightly(conn, NOW, **KW)
    assert out.status == "scored" and "6 day" in out.detail
    first_new = conn.execute(
        "SELECT min(day) FROM hold_signal WHERE day > %s", (newest,)
    ).fetchone()[0]
    seen = 0
    for iid, (was_held, entry) in before.items():
        row = conn.execute(
            "SELECT action, entry_day FROM hold_signal WHERE instrument_id=%s AND day=%s",
            (iid, first_new),
        ).fetchone()
        if row is None or not was_held:
            continue
        seen += 1
        assert row[0] in ("HOLD", "SELL")  # a stock held the evening before is never bought again
        assert row[0] == "SELL" or row[1] == entry  # and a hold keeps its entry day
    assert seen > 0
    assert hs.nightly(conn, NOW, **KW).status == "up_to_date"


def test_the_backfill_makes_the_history_again_from_a_day(conn):
    seed(conn, "2017-01-02", 1100)
    hs.nightly(conn, NOW, **KW)
    n = conn.execute("SELECT count(*) FROM hold_signal").fetchone()[0]
    mid = date(2020, 6, 1)
    out = hs.backfill(conn, mid, NOW, **{k: v for k, v in KW.items() if k != "score_from"})
    assert out.status == "scored"
    assert (
        conn.execute("SELECT count(*) FROM hold_signal").fetchone()[0] == n
    )  # the same days again


def test_nothing_to_score_is_reported_not_raised(conn):
    migrate(conn)
    assert hs.nightly(conn, NOW, **KW).status == "no_bars"
    seed(conn, "2019-06-03", 80)  # too few bars for any stock to be in the universe
    assert hs.nightly(conn, NOW, **KW).status == "too_little_history"
    assert conn.execute("SELECT count(*) FROM hold_signal").fetchone()[0] == 0
