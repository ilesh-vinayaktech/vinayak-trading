# ruff: noqa: E501
"""Rise odds: a model's estimate, per liquid stock and day, for the next 5 sessions, of two things (`kind`): 'rel', the chance it beats the median stock (a rank against the other stocks), and
'up', the chance it closes higher than today, judged from the stock's own history only (scripts/study_own_direction.py: with market-state features the 'up' model became a market-timing model, worse
than chance on later years; on own history alone it kept a small edge, top 1% rose 60% of the time against 47.5% for all stocks).

Why this and not hand-picked signs: scripts/study_signal_search.py and study_confluence.py tested twelve classic signs (crosses, breakouts, patterns, 3-of-N alignments) and found
no edge on later data; scripts/study_learned_signals.py then let gradient boosting learn from 21 features known at each day's close (returns, volume and delivery against their norms,
distance from the 52-week range, gaps to the averages, RSI, MACD histogram, band width, strength against the market) and judged it only on years it never saw: the top 5% by its
confidence beat the median stock 55 to 56% of the time over 5 sessions (edge about +0.5%), the bottom 25% only 45 to 46%, on two separate splits. A few tenths of a percent before
costs, a hit rate near 56%, never 70 to 80%: this ranks stocks, it does not promise a rise.

Walk-forward, always: a model is trained on rows that ended at least 2 x horizon + 10 days before its `train_end` (so no training window overlaps what it scores) and scores only days
from `train_end` on. The nightly run scores new days with the newest model allowed to score each, and trains a new one about every six weeks; `backfill` makes the history the same
way, one model per year, so a past score is what the model would really have said then. Prices here are float32 (a score is a rank, not money). Nothing here reads the system
clock: `now` is passed in."""

from __future__ import annotations

import hashlib
import pickle  # noqa: S403 (our own fitted model, read back only after its sha256 matches the stored one)
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
import psycopg

if TYPE_CHECKING:  # scikit-learn is imported where a model is fitted, so the API process (which only needs the constants and the tables) does not load it
    from sklearn.ensemble import HistGradientBoostingClassifier  # type: ignore[import-untyped]

Arr = np.ndarray[Any, Any]
HORIZON = 5
RETRAIN_DAYS = 45  # the nightly run trains a new model when the newest is older than this
MIN_TURNOVER_CR = 5.0  # a stock is scored only when it trades at least this many crore a day (20-day average), as the swing score does
HISTORY_FROM = date(2019, 9, 1)  # NSE delivery data begins in October 2019
LOOKBACK_DAYS = 520  # calendar days of bars a day's features need (252 sessions for the 52-week range, 120 for the band width)
MIN_LEAF = 800  # large leaves: a model that cannot memorise noise
FEATURES = (
    "r1", "r5", "r20", "r60", "vr1", "vr5", "dpct", "dpct5", "dratio", "rng", "loc",
    "d52h", "d52l", "g50", "g200", "slope50", "rsi", "macdh", "bwr", "rs20", "rs60",
)  # fmt: skip
OWN_FEATURES = tuple(f for f in FEATURES if f not in ("rs20", "rs60")) + (
    "vol20",
    "atr14",
    "up_days10",
    "r5_z",
)  # the stock's own history only: nothing about other stocks or the market
KINDS: dict[str, tuple[str, ...]] = {
    "rel": FEATURES,
    "up": OWN_FEATURES,
}  # the features each kind of model is fitted on


@dataclass(frozen=True)
class Panel:
    """Daily bars as days x stocks tables (float32)."""

    high: pd.DataFrame
    low: pd.DataFrame
    close: pd.DataFrame
    volume: pd.DataFrame
    delivery: pd.DataFrame


@dataclass(frozen=True)
class Outcome:
    status: str  # scored | up_to_date | no_bars | too_little_history
    detail: str


# --- the data ---------------------------------------------------------------------------------------------------------------


def load_panel(conn: psycopg.Connection, first: date, last: date) -> Panel:
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, high::float8, low::float8, close::float8, volume::float8, delivery_qty::float8"
        " FROM bar_1d WHERE source='nse' AND series='EQ' AND ts >= %s::date AND ts < %s::date + 1 ORDER BY instrument_id, ts, dataset_version DESC",
        (first, last),
    ).fetchall()
    df = pd.DataFrame(rows, columns=["iid", "d", "h", "l", "c", "v", "dq"])

    def mat(col: str) -> pd.DataFrame:
        return df.pivot(index="d", columns="iid", values=col).sort_index().astype("float32")

    return Panel(mat("h"), mat("l"), mat("c"), mat("v"), mat("dq"))


def load_splits(conn: psycopg.Connection) -> list[tuple[int, date]]:
    return [
        (int(i), d)
        for i, d in conn.execute(
            "SELECT instrument_id, ex_date FROM corporate_action WHERE kind IN ('split','bonus') AND status='ok'"
        )
    ]


# --- features and labels --------------------------------------------------------------------------------------------------------


def features(p: Panel) -> dict[str, pd.DataFrame]:
    """The features of every stock on every day (the 21 of the relative model and the own-history ones), each known at that day's close (never the next day's)."""
    c, h, lo, v, dq = p.close, p.high, p.low, p.volume, p.delivery
    rng = h - lo
    sma50, sma200, sma20 = (c.rolling(n, min_periods=n).mean() for n in (50, 200, 20))
    bw = 4 * c.rolling(20, min_periods=20).std() / sma20
    dpct = dq / v.where(v > 0) * 100
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    d = c.diff()
    rsi = 100 - 100 / (
        1
        + d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        / (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    )
    r20, r60 = c / c.shift(20) - 1, c / c.shift(60) - 1
    ret1 = c.pct_change()
    vol20 = ret1.rolling(20, min_periods=10).std() * 100
    r5 = c / c.shift(5) - 1
    return {
        "vol20": vol20,
        "atr14": rng.rolling(14, min_periods=14).mean() / c * 100,
        "up_days10": (ret1 > 0).astype("float32").rolling(10).sum(),
        "r5_z": r5
        / (
            vol20 / 100 * np.sqrt(5)
        ),  # the last 5 sessions' move in units of the stock's own usual 5-session move
        "r1": c / c.shift(1) - 1,
        "r5": c / c.shift(5) - 1,
        "r20": r20,
        "r60": r60,
        "vr1": v / v.shift(1).rolling(20, min_periods=15).mean(),
        "vr5": v.rolling(5).mean() / v.shift(5).rolling(20, min_periods=15).mean(),
        "dpct": dpct,
        "dpct5": dq.rolling(5).sum() / v.rolling(5).sum() * 100,
        "dratio": dpct / dpct.shift(1).rolling(20, min_periods=15).mean(),
        "rng": rng / rng.shift(1).rolling(14, min_periods=14).mean(),
        "loc": (c - lo) / rng.where(rng > 0),
        "d52h": c / c.rolling(252, min_periods=200).max() - 1,
        "d52l": c / c.rolling(252, min_periods=200).min() - 1,
        "g50": c / sma50 - 1,
        "g200": c / sma200 - 1,
        "slope50": sma50 / sma50.shift(10) - 1,
        "rsi": rsi,
        "macdh": (macd - macd.ewm(span=9, adjust=False).mean()) / c * 100,
        "bwr": bw / bw.rolling(120, min_periods=60).mean(),
        "rs20": r20.sub(r20.median(axis=1), axis=0),
        "rs60": r60.sub(r60.median(axis=1), axis=0),
    }


def liquid(p: Panel, min_turnover_cr: float = MIN_TURNOVER_CR) -> pd.DataFrame:
    """True where the stock's 20-day average traded value is at least `min_turnover_cr` crore."""
    return ((p.close * p.volume).rolling(20, min_periods=15).mean() / 1e7) >= min_turnover_cr


def _split_mask(p: Panel, splits: list[tuple[int, date]], reach: int, horizon: int) -> pd.DataFrame:
    """True where a split or bonus lies within `reach` sessions before or `horizon` after: prices there are not comparable."""
    bad = pd.DataFrame(False, index=p.close.index, columns=p.close.columns)
    idx = np.array(p.close.index, dtype="datetime64[D]")
    position = {int(c): k for k, c in enumerate(bad.columns)}  # the column of each stock
    for iid, ex in splits:
        if iid in position:
            i = int(np.searchsorted(idx, np.datetime64(ex)))
            bad.iloc[max(0, i - reach) : min(len(idx), i + horizon + 1), position[iid]] = True
    return bad


def excess(
    p: Panel,
    splits: list[tuple[int, date]],
    horizon: int = HORIZON,
    min_turnover_cr: float = MIN_TURNOVER_CR,
) -> pd.DataFrame:
    """The return over the next `horizon` sessions less the median liquid stock's, NaN where the stock is not liquid, a split is near or the future is not known yet."""
    fwd = p.close.shift(-horizon) / p.close - 1
    ok = (
        liquid(p, min_turnover_cr) & ~_split_mask(p, splits, 70, horizon) & fwd.notna()
    )  # 70: the longest look-back (60 sessions) must not cross a split either
    return fwd.sub(fwd.where(ok).median(axis=1), axis=0).where(ok)


def forward_return(
    p: Panel,
    splits: list[tuple[int, date]],
    horizon: int = HORIZON,
    min_turnover_cr: float = MIN_TURNOVER_CR,
) -> pd.DataFrame:
    """The plain return over the next `horizon` sessions, NaN where the stock is not liquid, a split is near or the future is not known yet."""
    fwd = p.close.shift(-horizon) / p.close - 1
    ok = liquid(p, min_turnover_cr) & ~_split_mask(p, splits, 70, horizon) & fwd.notna()
    return fwd.where(ok)


def target(
    p: Panel, splits: list[tuple[int, date]], kind: str, horizon: int = HORIZON
) -> pd.DataFrame:
    """What the model of this kind is trained to call: the excess return over the median stock ('rel') or the plain return ('up'); positive is the 'yes'."""
    return excess(p, splits, horizon) if kind == "rel" else forward_return(p, splits, horizon)


def _stack(
    feats: dict[str, pd.DataFrame], where: pd.DataFrame, names: tuple[str, ...] = FEATURES
) -> tuple[Arr, Arr, Arr]:
    """(X, day positions, stock positions) for the cells where `where` is true: one row per stock-day, columns in `names` order."""
    mask = where.to_numpy()
    X = np.column_stack([feats[k].to_numpy()[mask] for k in names]).astype("float32")
    days, stocks = np.nonzero(mask)
    return X, days, stocks


def training_set(
    p: Panel,
    feats: dict[str, pd.DataFrame],
    splits: list[tuple[int, date]],
    train_end: date,
    horizon: int = HORIZON,
    kind: str = "rel",
) -> tuple[Arr, Arr]:
    """(X, y): rows ending at least 2 x horizon + 10 days before `train_end`, y = 1 where the target of this kind is positive over the next `horizon` sessions."""
    ex = target(p, splits, kind, horizon)
    cutoff = np.datetime64(train_end - timedelta(days=2 * horizon + 10))
    early = np.array(ex.index, dtype="datetime64[D]") < cutoff
    where = ex.notna() & pd.DataFrame(
        np.broadcast_to(early[:, None], ex.shape), index=ex.index, columns=ex.columns
    )
    X, di, si = _stack(feats, where, KINDS[kind])
    y = (ex.to_numpy()[di, si] > 0).astype(np.int8)
    keep = ~np.isnan(X).all(axis=1)
    return X[keep], y[keep]


def fit(X: Arr, y: Arr, min_leaf: int = MIN_LEAF) -> HistGradientBoostingClassifier:
    """Every other row (neighbouring days are nearly the same example), strongly regularised: it can only find what is broad and repeated."""
    from sklearn.ensemble import HistGradientBoostingClassifier

    model = HistGradientBoostingClassifier(
        max_iter=200,
        learning_rate=0.05,
        max_leaf_nodes=15,
        min_samples_leaf=min_leaf,
        l2_regularization=5.0,
        random_state=0,
    )
    return model.fit(X[::2], y[::2])


def score_range(
    model: Any,
    p: Panel,
    feats: dict[str, pd.DataFrame],
    days: list[date],
    min_turnover_cr: float = MIN_TURNOVER_CR,
    kind: str = "rel",
) -> pd.DataFrame:
    """(day, iid, prob, pct) for every liquid stock on each of `days`; pct ranks the stocks of the same day (100 = the most likely 'yes' of this kind)."""
    wanted = np.isin(
        np.array(p.close.index, dtype="datetime64[D]"), np.array(days, dtype="datetime64[D]")
    )
    where = liquid(p, min_turnover_cr) & pd.DataFrame(
        np.broadcast_to(wanted[:, None], p.close.shape),
        index=p.close.index,
        columns=p.close.columns,
    )
    X, di, si = _stack(feats, where, KINDS[kind])
    keep = ~np.isnan(X).all(axis=1)
    X, di, si = X[keep], di[keep], si[keep]
    if len(X) == 0:
        return pd.DataFrame(columns=["day", "iid", "prob", "pct"])
    out = pd.DataFrame(
        {"day": p.close.index[di], "iid": p.close.columns[si], "prob": model.predict_proba(X)[:, 1]}
    )
    out["pct"] = out.groupby("day")["prob"].rank(pct=True) * 100
    return out


# --- storage ----------------------------------------------------------------------------------------------------------------------


def version_of(train_end: date, horizon: int = HORIZON, kind: str = "rel") -> str:
    """'h5-2026-01-01' for the relative model (the names already stored), 'h5up-2026-01-01' for the own-direction one."""
    return f"h{horizon}{'' if kind == 'rel' else kind}-{train_end.isoformat()}"


def save_model(
    conn: psycopg.Connection,
    model: Any,
    train_end: date,
    n_rows: int,
    now: datetime,
    horizon: int = HORIZON,
    kind: str = "rel",
) -> str:
    payload = pickle.dumps(model)
    version = version_of(train_end, horizon, kind)
    conn.execute(
        "INSERT INTO rise_odds_model (version, horizon, train_end, trained_at, n_rows, features, payload, sha256, kind) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (version) DO NOTHING",
        (
            version,
            horizon,
            train_end,
            now,
            n_rows,
            list(KINDS[kind]),
            payload,
            hashlib.sha256(payload).hexdigest(),
            kind,
        ),
    )
    return version


def load_model(conn: psycopg.Connection, version: str) -> Any:
    row = conn.execute(
        "SELECT payload, sha256, features, kind FROM rise_odds_model WHERE version=%s", (version,)
    ).fetchone()
    if row is None:
        raise KeyError(f"no rise-odds model {version}")
    payload, sha, names, kind = bytes(row[0]), row[1], list(row[2]), row[3]
    if hashlib.sha256(payload).hexdigest() != sha:
        raise ValueError(f"rise-odds model {version} does not match its stored hash")
    if names != list(KINDS[kind]):
        raise ValueError(
            f"rise-odds model {version} was fitted on other features than the code builds now"
        )
    return pickle.loads(payload)  # noqa: S301


def model_for(
    conn: psycopg.Connection, day: date, horizon: int = HORIZON, kind: str = "rel"
) -> tuple[str, date] | None:
    """The newest model of this kind allowed to score `day`: the one with the latest train_end on or before it."""
    row = conn.execute(
        "SELECT version, train_end FROM rise_odds_model WHERE horizon=%s AND kind=%s AND train_end <= %s ORDER BY train_end DESC LIMIT 1",
        (horizon, kind, day),
    ).fetchone()
    return None if row is None else (row[0], row[1])


def store_scores(
    conn: psycopg.Connection,
    scores: pd.DataFrame,
    version: str,
    horizon: int = HORIZON,
    kind: str = "rel",
) -> int:
    rows = [
        (pd.Timestamp(d).date(), int(i), horizon, float(pr), float(pc), version, kind)
        for d, i, pr, pc in scores[["day", "iid", "prob", "pct"]].itertuples(index=False)
    ]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO rise_odds (day, instrument_id, horizon, prob, pct, model_version, kind) VALUES (%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT (day, instrument_id, horizon, kind) DO UPDATE SET prob=EXCLUDED.prob, pct=EXCLUDED.pct, model_version=EXCLUDED.model_version",
            rows,
        )
    return len(rows)


# --- training and scoring jobs ----------------------------------------------------------------------------------------------------------


def _latest_bar_day(conn: psycopg.Connection) -> date | None:
    row = conn.execute(
        "SELECT max((ts AT TIME ZONE 'Asia/Kolkata')::date) FROM bar_1d WHERE source='nse' AND series='EQ'"
    ).fetchone()
    return None if row is None else row[0]


def train_model(
    conn: psycopg.Connection,
    train_end: date,
    now: datetime,
    panel: Panel | None = None,
    min_leaf: int = MIN_LEAF,
    kind: str = "rel",
    feats: dict[str, pd.DataFrame] | None = None,
) -> str | None:
    """Fit and save the model of this kind that may score days from `train_end` on; None when there is too little history to train on."""
    p = panel if panel is not None else load_panel(conn, HISTORY_FROM, train_end)
    X, y = training_set(
        p, feats if feats is not None else features(p), load_splits(conn), train_end, kind=kind
    )
    if len(y) < 4 * min_leaf or y.min() == y.max():
        return None
    return save_model(conn, fit(X, y, min_leaf), train_end, len(y), now, kind=kind)


def nightly(conn: psycopg.Connection, now: datetime, min_leaf: int = MIN_LEAF) -> Outcome:
    """Score the bar days not scored yet (normally just the newest) for each kind, each day with the newest model of that kind allowed to score it, first training a new one when there is
    none or it is over RETRAIN_DAYS old."""
    latest = _latest_bar_day(conn)
    if latest is None:
        return Outcome("no_bars", "there are no daily bars")
    behind: dict[str, date | None] = {}
    for kind in KINDS:
        last_scored = conn.execute(
            "SELECT max(day) FROM rise_odds WHERE kind=%s", (kind,)
        ).fetchone()[0]  # type: ignore[index]
        if last_scored is None or last_scored < latest:
            behind[kind] = last_scored
    if not behind:
        return Outcome("up_to_date", f"scores are already in for {latest}")
    stale = [
        k
        for k in behind
        if (m := model_for(conn, latest, kind=k)) is None or (latest - m[1]).days > RETRAIN_DAYS
    ]
    firsts = {k: latest if ls is None else ls + timedelta(days=1) for k, ls in behind.items()}
    p = load_panel(
        conn,
        HISTORY_FROM if stale else min(firsts.values()) - timedelta(days=LOOKBACK_DAYS),
        latest,
    )
    feats = features(p)
    for kind in stale:
        train_model(conn, latest, now, panel=p, min_leaf=min_leaf, kind=kind, feats=feats)
    scored, days_done = 0, set()
    for kind, first in firsts.items():
        by_version: dict[str, list[date]] = {}
        for d in (d for d in p.close.index if first <= d <= latest):
            m = model_for(conn, d, kind=kind)
            if (
                m is not None
            ):  # a day before the first model's train_end cannot be scored without looking ahead: it is left out
                by_version.setdefault(m[0], []).append(d)
        for version, days in by_version.items():
            part = score_range(load_model(conn, version), p, feats, days, kind=kind)
            scored += store_scores(conn, part, version, kind=kind) if len(part) else 0
            days_done.update(days)
    if not days_done:
        return Outcome("too_little_history", "there are too few bars to train a model")
    return Outcome(
        "scored",
        f"{scored} scores for {len(days_done)} day{'s' if len(days_done) != 1 else ''} up to {latest}",
    )


def backfill(
    conn: psycopg.Connection,
    since: date,
    now: datetime,
    until: date | None = None,
    min_leaf: int = MIN_LEAF,
    kinds: tuple[str, ...] | None = None,
) -> int:
    """The history, walk-forward: for each kind (all, unless `kinds` names some) and each year from `since`, a model trained on the data before 1 January scores that year. Returns the number of scores stored."""
    last = until or _latest_bar_day(conn)
    if last is None:
        return 0
    p = load_panel(conn, HISTORY_FROM, last)
    feats = features(p)
    splits = load_splits(conn)
    total = 0
    for kind in kinds or tuple(KINDS):
        for year in range(since.year, last.year + 1):
            train_end = date(year, 1, 1)
            X, y = training_set(p, feats, splits, train_end, kind=kind)
            if len(y) < 4 * min_leaf or y.min() == y.max():
                continue
            version = save_model(conn, fit(X, y, min_leaf), train_end, len(y), now, kind=kind)
            days = [
                d
                for d in p.close.index
                if max(since, train_end) <= d <= min(last, date(year, 12, 31))
            ]
            part = score_range(load_model(conn, version), p, feats, days, kind=kind)
            total += store_scores(conn, part, version, kind=kind) if len(part) else 0
    return total
