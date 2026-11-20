# ruff: noqa: E501
"""The hold signal: a daily BUY / HOLD / SELL call per liquid stock, from the rule frozen on 2026-11-19 (research: scripts/study_hold_signal_folds.py, frozen spec data/research/winner_v2/frozen_HOLD_SIGNAL_V1.json).

The rule, unchanged from the study. A pooled gradient-boosting model reads 31 price-only features of each stock's own bars (no volume, no fundamentals, nothing about other stocks except the ranking) and says how
likely it is to beat the median stock over the next 5 sessions, counted from the next open. Each day the stocks are RANKED by that chance (0 to 100; 100 = most likely). A flat stock is BOUGHT (at the next open) when its rank
is 90 or more; a held stock is SOLD (at the next open) when its rank falls to 20 or less; in between it is held. No stop, no fixed holding time. The portfolio reading is at most 10 positions, highest rank first.
The model for a day was trained on data that ended two calendar years earlier (a day of 2026 uses the model trained to 2024-12-31): the year between is a gap, as in the study, so a score is what the model would have said then.
The universe is fixed on development data: stocks with a median daily traded value of Rs 5 crore or more over 400+ bars up to 2024-12-31 (so a stock listed since is not scored).
Evidence, stated plainly: development years 2022-2024, +0.29% per trade over the market after real costs (95% interval +0.10 to +0.49); the 2025-26 window, read once on the owner's instruction outside the holdout policy's batch route (non-confirmatory),
+0.81% per trade over the market while the market fell. Much of that gain is which stocks the model keeps, not timing; it is long-only; it is not a forecast of any one stock. Prices are Kite's adjusted daily bars.
Nothing here reads the system clock: `now` is passed in."""

from __future__ import annotations

import hashlib
import pickle  # noqa: S403 (our own fitted model, read back only after its sha256 matches the stored one)
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
import psycopg

from algo.market.rise_odds import Outcome

Arr = np.ndarray[Any, Any]
HORIZON = 5
BUY_AT = 90.0  # a flat stock whose rank is at least this is bought
SELL_AT = 20.0  # a held stock whose rank falls to this or below is sold
MAX_POSITIONS = 10  # the portfolio reading: at most this many, highest rank first
MIN_TURNOVER_CR = 5.0
MIN_BARS = 400
MIN_STOCKS = 30  # a day with fewer ranked stocks is not ranked
UNIVERSE_END = date(2024, 12, 31)  # the universe is chosen on development data only
HISTORY_FROM = date(2016, 1, 1)  # Kite's daily history begins here
SCORE_FROM = date(2022, 1, 1)  # the validated years: 2022-2024 development, 2025-26 read once
MODEL_PARAMS: dict[str, Any] = {
    "max_depth": 4,
    "learning_rate": 0.05,
    "max_iter": 200,
    "min_samples_leaf": 500,
    "l2_regularization": 5.0,
    "random_state": 0,
}
FEATURES = (
    "ret1", "ret2", "ret3", "ret5", "ret10", "ret20", "ret60", "range_atr", "body", "up_wick", "lo_wick", "close_pos", "gap_atr",
    "dist_sma20", "dist_sma50", "dist_sma200", "pos20", "pos252", "days_since_hi20", "streak", "inside", "nr7", "atr_pct", "vol_ratio",
    "r_breakout20", "r_breakdown20", "r_oversold_up", "r_overbought", "r_trend", "r_bull_engulf", "r_bear_engulf",
)  # fmt: skip
_NEEDED = [
    "ret60",
    "dist_sma200",
    "pos252",
]  # a row without these has too little history to be scored


# --- features and labels -----------------------------------------------------------------------------------------------------------


def features_of(d: pd.DataFrame) -> pd.DataFrame:
    """The 31 features of ONE stock from its adjusted bars (columns o, h, l, c; a date index), each known at that day's close. Scale-free: returns in the stock's own volatility units, distances in ATR units."""
    o, h, lo, c = (d[k].astype("float64") for k in ("o", "h", "l", "c"))
    pc = c.shift(1)
    atr = (
        pd.concat([h - lo, (h - pc).abs(), (lo - pc).abs()], axis=1)
        .max(axis=1)
        .rolling(14, min_periods=14)
        .mean()
    )
    lr = pd.Series(
        np.log(c / pc), index=d.index
    )  # a Series (numpy's stubs type the log of a Series as a bare array)
    vol20 = lr.rolling(20, min_periods=15).std()
    rng = (h - lo).replace(0, np.nan)
    f = pd.DataFrame(index=d.index)
    for k in (1, 2, 3, 5, 10, 20, 60):
        f[f"ret{k}"] = np.log(c / c.shift(k)) / (vol20 * np.sqrt(k))
    f["range_atr"] = (h - lo) / atr
    f["body"] = (c - o) / rng
    f["up_wick"] = (h - np.maximum(o, c)) / rng
    f["lo_wick"] = (np.minimum(o, c) - lo) / rng
    f["close_pos"] = (c - lo) / rng
    f["gap_atr"] = (o - pc) / atr
    for k in (20, 50, 200):
        f[f"dist_sma{k}"] = (c - c.rolling(k, min_periods=k).mean()) / atr
    for k in (20, 252):
        hi, low = (
            h.rolling(k, min_periods=int(k * 0.8)).max(),
            lo.rolling(k, min_periods=int(k * 0.8)).min(),
        )
        f[f"pos{k}"] = (c - low) / (hi - low).replace(0, np.nan)
    f["days_since_hi20"] = h.rolling(20).apply(lambda x: 19 - int(np.argmax(x)), raw=True)
    up = (lr > 0).astype(int)
    grp = (up != up.shift()).cumsum()
    f["streak"] = up.groupby(grp).cumcount().add(1) * np.where(up == 1, 1, -1)
    f["inside"] = ((h < h.shift()) & (lo > lo.shift())).astype(float)
    f["nr7"] = ((h - lo) == (h - lo).rolling(7).min()).astype(float)
    f["atr_pct"] = atr / c
    f["vol_ratio"] = vol20 / lr.rolling(100, min_periods=60).std()
    f["r_breakout20"] = (c > h.shift().rolling(20).max()).astype(float)
    f["r_breakdown20"] = (c < lo.shift().rolling(20).min()).astype(float)
    f["r_oversold_up"] = ((f["ret3"] < -1.5) & (c > c.rolling(200, min_periods=200).mean())).astype(
        float
    )
    f["r_overbought"] = (f["ret3"] > 1.5).astype(float)
    f["r_trend"] = (
        (c > c.rolling(50).mean()) & (c.rolling(50).mean() > c.rolling(200, min_periods=200).mean())
    ).astype(float)
    f["r_bull_engulf"] = (
        (c > o) & (c.shift() < o.shift()) & (c >= o.shift()) & (o <= c.shift())
    ).astype(float)
    f["r_bear_engulf"] = (
        (c < o) & (c.shift() > o.shift()) & (c <= o.shift()) & (o >= c.shift())
    ).astype(float)
    f["fwd"] = (
        c.shift(-HORIZON) / o.shift(-1) - 1
    )  # the return from the next open to the close 5 sessions later: the label, never a feature
    return f[[*FEATURES, "fwd"]]


def feature_frames(bars: dict[int, pd.DataFrame]) -> dict[int, pd.DataFrame]:
    return {iid: features_of(d) for iid, d in bars.items()}


def assemble(
    frames: dict[int, pd.DataFrame], *, with_target: bool, min_stocks: int = MIN_STOCKS
) -> pd.DataFrame:
    """Long rows (iid, date, the 31 features, fwd): `with_target` keeps only rows whose future is known and adds `excess` (the return less that day's median stock), the training label."""
    if not frames:
        return pd.DataFrame(columns=["iid", "date", *FEATURES, "fwd"])
    df = (
        pd.concat([f.assign(iid=iid) for iid, f in frames.items()])
        .rename_axis("date")
        .reset_index()
    )
    df = df.replace([np.inf, -np.inf], np.nan).dropna(
        subset=[*_NEEDED, *(["fwd"] if with_target else [])]
    )
    if with_target:
        df["excess"] = df["fwd"] - df.groupby("date")["fwd"].transform("median")
    df = df[df.groupby("date")["iid"].transform("size") >= min_stocks]
    return df.sort_values(["iid", "date"]).reset_index(drop=True)


def build_rows(
    bars: dict[int, pd.DataFrame], *, with_target: bool, min_stocks: int = MIN_STOCKS
) -> pd.DataFrame:
    return assemble(feature_frames(bars), with_target=with_target, min_stocks=min_stocks)


def train_end_for(day: date) -> date:
    """The model that may score `day` was trained on data to the end of the year two years before it (the year between is a gap)."""
    return date(day.year - 2, 12, 31)


def training_set(rows: pd.DataFrame, train_end: date) -> tuple[Arr, Arr]:
    """(X, y) from the labelled rows dated on or before `train_end`; y = 1 where the stock beat that day's median stock."""
    r = rows[rows["date"] <= pd.Timestamp(train_end)]
    return r[list(FEATURES)].to_numpy(dtype="float64"), (r["excess"] > 0).to_numpy(dtype="int8")


def fit(X: Arr, y: Arr, min_leaf: int | None = None) -> Any:
    from sklearn.ensemble import HistGradientBoostingClassifier  # type: ignore[import-untyped]

    params = {**MODEL_PARAMS, **({} if min_leaf is None else {"min_samples_leaf": min_leaf})}
    return HistGradientBoostingClassifier(**params).fit(X, y)


def score(model: Any, rows: pd.DataFrame) -> pd.DataFrame:
    """(day, iid, prob, rank_pct) for every row: rank_pct ranks the stocks of the same day (100 = the most likely to beat the median stock)."""
    if rows.empty:
        return pd.DataFrame(columns=["day", "iid", "prob", "rank_pct"])
    out = pd.DataFrame(
        {
            "day": rows["date"].to_numpy(),
            "iid": rows["iid"].to_numpy(),
            "prob": model.predict_proba(rows[list(FEATURES)].to_numpy(dtype="float64"))[:, 1],
        }
    )
    out["rank_pct"] = out.groupby("day")["prob"].rank(pct=True) * 100
    return out


def advance(rank_pct: Arr, in_pos: Arr, entry: Arr, day: date) -> tuple[Arr, Arr, Arr]:
    """One day of the rule for many stocks: a flat stock at BUY_AT or more is bought, a held stock at SELL_AT or less is sold, a held stock otherwise stays. Returns (action, in_position after, entry day)."""
    buy = ~in_pos & (rank_pct >= BUY_AT)
    sell = in_pos & (rank_pct <= SELL_AT)
    hold = in_pos & ~sell
    action = np.where(buy, "BUY", np.where(sell, "SELL", np.where(hold, "HOLD", "NONE")))
    new_entry = entry.copy()
    new_entry[buy] = day
    new_entry[sell] = None
    return action, buy | hold, new_entry


# --- data --------------------------------------------------------------------------------------------------------------------------

# Kite's adjustment of a few schemes of arrangement is wrong (one stock showed Rs 0.15 where NSE showed Rs 620 before the event): an instrument's history before its last unexplained one-day jump (more than 4x or under 0.25x) is dropped.
_GUARD = (
    "LEFT JOIN (SELECT instrument_id, max(ts) AS jts FROM (SELECT instrument_id, ts, close / NULLIF(lag(close) OVER (PARTITION BY instrument_id ORDER BY ts), 0) AS r FROM bar_1d WHERE source='kite') t"
    " WHERE r > 4 OR r < 0.25 GROUP BY instrument_id) lj ON lj.instrument_id = k.instrument_id"
)


def universe(
    conn: psycopg.Connection,
    end: date = UNIVERSE_END,
    min_turnover_cr: float = MIN_TURNOVER_CR,
    min_bars: int = MIN_BARS,
) -> list[int]:
    """Equity stocks (those with NSE EQ bars) whose median daily traded value up to `end` is at least `min_turnover_cr` crore over at least `min_bars` Kite bars."""
    rows = conn.execute(
        "SELECT k.instrument_id FROM bar_1d k "
        + _GUARD
        + " WHERE k.source='kite' AND (lj.jts IS NULL OR k.ts >= lj.jts) AND k.ts >= %s::date AND k.ts < %s::date + 1"
        " AND k.instrument_id IN (SELECT DISTINCT instrument_id FROM bar_1d WHERE source='nse' AND series='EQ')"
        " GROUP BY k.instrument_id HAVING count(*) >= %s AND percentile_cont(0.5) WITHIN GROUP (ORDER BY k.close * k.volume / 1e7) >= %s ORDER BY 1",
        (HISTORY_FROM, end, min_bars, min_turnover_cr),
    ).fetchall()
    return [int(r[0]) for r in rows]


def load_bars(conn: psycopg.Connection, ids: list[int], last: date) -> dict[int, pd.DataFrame]:
    rows = conn.execute(
        "SELECT DISTINCT ON (k.instrument_id, k.ts) k.instrument_id, (k.ts AT TIME ZONE 'Asia/Kolkata')::date, k.open::float8, k.high::float8, k.low::float8, k.close::float8 FROM bar_1d k "
        + _GUARD
        + " WHERE k.source='kite' AND (lj.jts IS NULL OR k.ts >= lj.jts) AND k.instrument_id = ANY(%s) AND k.ts >= %s::date AND k.ts < %s::date + 1 ORDER BY k.instrument_id, k.ts, k.dataset_version DESC",
        (ids, HISTORY_FROM, last),
    ).fetchall()
    df = pd.DataFrame(rows, columns=["iid", "d", "o", "h", "l", "c"])
    df["d"] = pd.to_datetime(df["d"])
    return {int(i): g.set_index("d").drop(columns="iid").sort_index() for i, g in df.groupby("iid")}  # type: ignore[arg-type]


def latest_bar_day(conn: psycopg.Connection) -> date | None:
    row = conn.execute(
        "SELECT max((ts AT TIME ZONE 'Asia/Kolkata')::date) FROM bar_1d WHERE source='kite'"
    ).fetchone()
    return None if row is None else row[0]


# --- storage -----------------------------------------------------------------------------------------------------------------------


def version_of(train_end: date) -> str:
    return f"hold1-{train_end.isoformat()}"


def save_model(
    conn: psycopg.Connection, model: Any, train_end: date, n_rows: int, now: datetime
) -> str:
    payload = pickle.dumps(model)
    version = version_of(train_end)
    conn.execute(
        "INSERT INTO hold_signal_model (version, train_end, trained_at, n_rows, features, payload, sha256) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (version) DO NOTHING",
        (
            version,
            train_end,
            now,
            n_rows,
            list(FEATURES),
            payload,
            hashlib.sha256(payload).hexdigest(),
        ),
    )
    return version


def load_model(conn: psycopg.Connection, version: str) -> Any:
    row = conn.execute(
        "SELECT payload, sha256, features FROM hold_signal_model WHERE version=%s", (version,)
    ).fetchone()
    if row is None:
        raise KeyError(f"no hold-signal model {version}")
    payload, sha, names = bytes(row[0]), row[1], list(row[2])
    if hashlib.sha256(payload).hexdigest() != sha:
        raise ValueError(f"hold-signal model {version} does not match its stored hash")
    if names != list(FEATURES):
        raise ValueError(
            f"hold-signal model {version} was fitted on other features than the code builds now"
        )
    return pickle.loads(payload)  # noqa: S301


def _prior_state(conn: psycopg.Connection) -> dict[int, tuple[bool, date | None]]:
    """Where each stock stood after its newest stored day: held (and since when) or flat."""
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id) instrument_id, in_position, entry_day FROM hold_signal ORDER BY instrument_id, day DESC"
    ).fetchall()
    return {int(i): (bool(p), e) for i, p, e in rows}


def _store(conn: psycopg.Connection, rows: list[tuple[Any, ...]]) -> int:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO hold_signal (day, instrument_id, prob, rank_pct, action, in_position, entry_day, model_version) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT (day, instrument_id) DO UPDATE SET prob=EXCLUDED.prob, rank_pct=EXCLUDED.rank_pct, action=EXCLUDED.action, in_position=EXCLUDED.in_position, entry_day=EXCLUDED.entry_day, model_version=EXCLUDED.model_version",
            rows,
        )
    return len(rows)


# --- the nightly run ---------------------------------------------------------------------------------------------------------------


def nightly(
    conn: psycopg.Connection,
    now: datetime,
    *,
    score_from: date = SCORE_FROM,
    universe_end: date = UNIVERSE_END,
    min_bars: int = MIN_BARS,
    min_turnover_cr: float = MIN_TURNOVER_CR,
    min_stocks: int = MIN_STOCKS,
    min_leaf: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> Outcome:
    """Score every bar day not scored yet (normally just the newest; the first run, every day from `score_from`), each with the model of its year, training a model first when it is missing, and carry each stock's
    held / flat state forward day by day. A day whose model cannot be trained (too little history) is left out, never scored with a later model."""
    latest = latest_bar_day(conn)
    if latest is None:
        return Outcome("no_bars", "there are no Kite daily bars")
    last_done = conn.execute("SELECT max(day) FROM hold_signal").fetchone()[0]  # type: ignore[index]
    if last_done is not None and last_done >= latest:
        return Outcome("up_to_date", f"signals are already in for {latest}")
    first = score_from if last_done is None else last_done + timedelta(days=1)
    ids = universe(conn, universe_end, min_turnover_cr, min_bars)
    if not ids:
        return Outcome("too_little_history", "no stock has enough history to be scored")
    say = progress or (lambda _m: None)
    frames = feature_frames(load_bars(conn, ids, latest))
    say(f"features for {len(ids)} stocks")
    rows = assemble(frames, with_target=False, min_stocks=min_stocks)
    todo = rows[(rows["date"] >= pd.Timestamp(first)) & (rows["date"] <= pd.Timestamp(latest))]
    if todo.empty:
        return Outcome("too_little_history", "there are too few bars to rank a day")
    labelled: pd.DataFrame | None = None
    state = _prior_state(conn)
    out: list[tuple[Any, ...]] = []
    days_done: set[date] = set()
    for year in sorted(set(todo["date"].dt.year.astype(int).tolist())):
        part = todo[todo["date"].dt.year == year]
        train_end = train_end_for(date(year, 1, 1))
        version = version_of(train_end)
        have = conn.execute(
            "SELECT 1 FROM hold_signal_model WHERE version=%s", (version,)
        ).fetchone()
        if have is None:
            if labelled is None:
                labelled = assemble(frames, with_target=True, min_stocks=min_stocks)
            X, y = training_set(labelled, train_end)
            if len(y) < 4 * (min_leaf or MODEL_PARAMS["min_samples_leaf"]) or y.min() == y.max():
                continue  # no model may score this year
            save_model(conn, fit(X, y, min_leaf), train_end, len(y), now)
            say(f"trained {version} on {len(y):,} rows")
        sc = score(load_model(conn, version), part)
        for day, g in sc.groupby("day"):
            d = pd.Timestamp(str(day)).date()
            iids = g["iid"].to_numpy()
            in_pos = np.array([state.get(int(i), (False, None))[0] for i in iids], dtype=bool)
            entry = np.array([state.get(int(i), (False, None))[1] for i in iids], dtype=object)
            action, in_pos2, entry2 = advance(g["rank_pct"].to_numpy(), in_pos, entry, d)
            for k, i in enumerate(iids):
                state[int(i)] = (bool(in_pos2[k]), entry2[k])
                out.append(
                    (
                        d,
                        int(i),
                        float(g["prob"].iloc[k]),
                        float(g["rank_pct"].iloc[k]),
                        str(action[k]),
                        bool(in_pos2[k]),
                        entry2[k],
                        version,
                    )
                )
            days_done.add(d)
    if not days_done:
        return Outcome("too_little_history", "there are too few bars to train a model")
    n = _store(conn, out)
    return Outcome(
        "scored",
        f"{n} signals for {len(days_done)} day{'s' if len(days_done) != 1 else ''} up to {max(days_done)}",
    )


def backfill(conn: psycopg.Connection, since: date, now: datetime, **kw: Any) -> Outcome:
    """The history again from `since` (every stored signal on or after it is dropped first), so the held / flat state is one unbroken walk-forward run from that day on."""
    conn.execute("DELETE FROM hold_signal WHERE day >= %s", (since,))
    return nightly(conn, now, score_from=since, **kw)
