# ruff: noqa: E501
"""The forecast job (TODO 6.5): build the evidence from the stored zone and the index series, make the predictions of algo.market.predict, log them in
`prediction_log`, and resolve earlier ones once their horizon has passed. `backfill` writes the walk-forward history (each day predicted by a model fitted only on
outcomes known by then); `tonight` makes the live predictions for the latest trading day (the model fitted on every resolved outcome) and resolves what is due."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import numpy as np
import psycopg
from psycopg.types.json import Jsonb

from algo.data import global_markets
from algo.market import predict, sectors
from algo.market.predict import Arr
from algo.market.zone import SIGNALS

Table = tuple[Arr, Arr, Arr, Arr, list[str], list[str]]
HORIZONS = (1, 5)
PRODUCTS = (
    "night",
    "morning",
)  # night: made after the close, before the US session (no overnight inputs); morning: made at 08:50 IST with the US close
# A frozen research candidate (docs/forecast/candidate_morning7_spec.md): the market model with US overnight moves and recent price only. It is logged live in
# parallel with the production morning model from the same run, on the same inputs, as its own version; it has no walk-forward history here (it was chosen after
# seeing that history, so only forward days can confirm it), is never shown as the forecast, and never touches the sector model.
CANDIDATES = {"morning7": ("ret_1d", "ret_5d", "ret_21d", "adv_share", "us_sp", "us_nq", "us_vix")}
CUTOFFS = {"night": "21:45 IST, after the Indian close", "morning": "08:50 IST, with the US close"}
MARKET = "MARKET"
DAYS = 2200  # about 8.5 years of index history: sectors whose index starts later than this are left out
OVERNIGHT = (
    "us_sp",
    "us_nq",
    "us_vix",
)  # what the US did overnight, in %: S&P 500, Nasdaq, the US VIX (the last session before the day being forecast)
M_NAMES = (*SIGNALS, "fear_greed", "ret_1d", "ret_5d", "ret_21d", "adv_share", *OVERNIGHT)


def version(product: str) -> str:
    """Each product is its own model: its own features, its own record, never mixed with the other's."""
    return f"{predict.MODEL_VERSION}-{product}"


def names_for(names: tuple[str, ...], product: str) -> list[str]:
    if product in CANDIDATES:
        return [n for n in names if n in CANDIDATES[product]]
    return [n for n in names if product == "morning" or n not in OVERNIGHT]


S_NAMES = (
    "ret_1d",
    "ret_5d",
    "ret_21d",
    "rs_ratio",
    "rs_momentum",
    "rotation",
    "above_50",
    "above_200",
    "mkt_fear_greed",
    "mkt_ret_1d",
    *OVERNIGHT,
)


@dataclass
class Data:
    dates: list[date]
    series: dict[str, list[float]]  # MARKET and every sector: one close per date
    market_x: dict[int, list[float]]  # position -> features
    sector_x: dict[int, dict[str, list[float]]]


def _pct(xs: list[float], i: int, n: int) -> float:
    return 100.0 * (xs[i] / xs[i - n] - 1) if i >= n and xs[i - n] else 0.0


def _next_day(dates: list[date], i: int) -> date:
    """The Indian session after position i: the next stored date, or for the latest day the next weekday (holidays are not known ahead)."""
    if i + 1 < len(dates):
        return dates[i + 1]
    d = dates[i] + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def load(conn: psycopg.Connection) -> Data:
    dates, bench, sec = sectors.load(conn, days=DAYS)
    us = [global_markets.series(conn, s) for s in ("SP500", "NASDAQ", "VIXUS")]
    regime = {
        r[0]: r
        for r in conn.execute(
            "SELECT day, fear_greed, components, advancers, decliners FROM market_regime_daily"
        )
    }
    data = Data(dates, {MARKET: bench, **sec}, {}, {})
    for i, d in enumerate(dates):
        if d not in regime or i < 21:
            continue
        _, fg, comps, adv, dec = regime[d]
        comps = comps or {}
        fgv = (
            np.nan if fg is None else float(fg)
        )  # a figure that is missing stays missing (the model fills it from its training period only)
        nxt = _next_day(dates, i)
        night = [
            np.nan if (r := global_markets.last_session_return(s, nxt)) is None else r for s in us
        ]  # not in yet is missing, never "no move"
        data.market_x[i] = [
            *(np.nan if comps.get(k) is None else float(comps[k]) for k in SIGNALS),
            fgv, _pct(bench, i, 1), _pct(bench, i, 5), _pct(bench, i, 21), 100.0 * adv / (adv + dec) if adv + dec else np.nan, *night,
        ]  # fmt: skip
        if i >= 199:
            data.sector_x[i] = {
                r.name: [
                    *(np.nan if v is None else 100 * v for v in (r.ret_1d, r.ret_5d, r.ret_21d)), r.rs_ratio - 100, r.rs_momentum - 100,
                    r.score, float(r.above_50), float(r.above_200), fgv, _pct(bench, i, 1), *night,
                ]
                for r in sectors.rotation(sec, bench, at=i)
            }  # fmt: skip
    return data


def _outcome(series: list[float], i: int, h: int) -> tuple[float, float]:
    """(1.0 / 0.0 for up / not up, the return) at position i over h days; (nan, nan) when the horizon is not over."""
    if i + h >= len(series):
        return float("nan"), float("nan")
    r = series[i + h] / series[i] - 1
    return float(r > 0), r


def _tables(data: Data, h: int, product: str) -> dict[str, Table]:
    """For MARKET and for the pooled sectors: features (the product's own columns), outcome, position, return, the subject of each row and the feature names.
    A morning row needs the overnight figures: a day without them gets no morning forecast and trains nothing."""
    out = {}
    for kind, full in ((MARKET, M_NAMES), ("SECTORS", S_NAMES)):
        names = names_for(full, product)
        cols = [full.index(n) for n in names]
        if product in CANDIDATES and kind != MARKET:
            continue  # a candidate is a market model only
        night = [full.index(n) for n in OVERNIGHT] if product != "night" else []
        xs, ys, pos, ret, who = [], [], [], [], []
        for i in sorted(data.market_x):
            items = {MARKET: data.market_x[i]} if kind == MARKET else data.sector_x.get(i, {})
            for name, x in items.items():
                if any(np.isnan(x[c]) for c in night):
                    continue
                y, r = _outcome(data.series[name], i, h)
                xs.append([x[c] for c in cols])
                ys.append(y)
                pos.append(i)
                ret.append(r)
                who.append(name)  # noqa: E702
        out[kind] = (np.array(xs), np.array(ys), np.array(pos), np.array(ret), who, list(names))
    return out


def _rows(
    data: Data,
    h: int,
    live: bool,
    p: Arr,
    mask: Arr,
    t: Table,
    product: str,
    train_through: Callable[[int], date | None],
    made_at: datetime | None,
    models: predict.Model | None = None,
) -> list[tuple[object, ...]]:
    """One prediction_log row per masked row, with its evidence: the feature values as seen (None where missing), when it was made and the last day its model learned from."""
    x, y, pos, ret, who, names = t
    out: list[tuple[object, ...]] = []
    for k in np.flatnonzero(mask):
        ev = models.evidence(x[k]) if models is not None else []
        feats = {
            n: (None if np.isnan(v) else round(float(v), 6))
            for n, v in zip(names, x[k], strict=True)
        }
        out.append((data.dates[int(pos[k])], who[k], h, version(product), live, float(p[k]), Jsonb(ev), None if np.isnan(y[k]) else bool(y[k]), None if np.isnan(ret[k]) else float(ret[k]), None if np.isnan(y[k]) else data.dates[min(int(pos[k]) + h, len(data.dates) - 1)], made_at, Jsonb(feats), train_through(k)))  # fmt: skip
    return out


COLS = "as_of, subject, horizon_days, model_version, live, p_up, evidence, outcome_up, realized, resolved_on, made_at, features, train_through"
SQL_LIVE = f"INSERT INTO prediction_log ({COLS}) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (as_of, subject, horizon_days, model_version, live) DO NOTHING"  # a live call is never rewritten
SQL_WALK = (
    f"INSERT INTO prediction_log ({COLS}) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
    " ON CONFLICT (as_of, subject, horizon_days, model_version, live) DO UPDATE SET p_up=EXCLUDED.p_up, evidence=EXCLUDED.evidence, outcome_up=EXCLUDED.outcome_up, realized=EXCLUDED.realized,"
    " resolved_on=EXCLUDED.resolved_on, features=EXCLUDED.features, train_through=EXCLUDED.train_through"
)  # a walk-forward row is re-derivable from the data, so a rebuild may replace it


def backfill(conn: psycopg.Connection) -> int:
    """The walk-forward history of both products for the market and the sectors, at every horizon. Returns rows written."""
    data = load(conn)
    n = 0
    for product in PRODUCTS:
        for h in HORIZONS:
            for t in _tables(data, h, product).values():
                x, y, pos, _, _, names = t
                if len(x) == 0:
                    continue
                p, mask, fit_at = predict.walk_forward_detail(x, y, pos, h, names)

                def learned_to(k: int, fit_at: Arr = fit_at, h: int = h) -> date | None:
                    return data.dates[max(0, int(fit_at[k]) - h)]

                rows = _rows(data, h, False, p, mask, t, product, learned_to, None)
                with conn.cursor() as cur:
                    cur.executemany(SQL_WALK, rows)
                n += len(rows)
    return n


def tonight(conn: psycopg.Connection, product: str, now: datetime) -> int:
    """Live predictions of one product for the latest day (a morning forecast only when the overnight figures are in), then resolve every earlier prediction whose
    horizon is over. A live prediction already made is left as it was. Returns rows written or resolved."""
    data = load(conn)
    if not data.market_x:
        return 0
    last = max(data.market_x)
    n = 0
    for h in HORIZONS:
        for t in _tables(data, h, product).values():
            x, y, pos, _, _, names = t
            known = (pos + h <= last) & ~np.isnan(y)
            model = predict.fit(x[known], y[known], names)
            today = pos == last
            if model is None or not today.any():
                continue
            p = np.full(len(x), np.nan)
            p[today] = model.p_up(x[today])
            rows = []

            def learned_to(_k: int, h: int = h) -> date | None:
                return data.dates[max(0, last - h)]

            for k in np.flatnonzero(today):
                rows += _rows(
                    data, h, True, p, np.arange(len(x)) == k, t, product, learned_to, now, model
                )
            with conn.cursor() as cur:
                cur.executemany(SQL_LIVE, rows)
            n += len(rows)
    for as_of, subject, h in conn.execute(
        "SELECT as_of, subject, horizon_days FROM prediction_log WHERE outcome_up IS NULL"
    ).fetchall():
        if subject not in data.series or as_of not in data.dates:
            continue
        i = data.dates.index(as_of)
        up, r = _outcome(data.series[subject], i, h)
        if not np.isnan(up):
            conn.execute(
                "UPDATE prediction_log SET outcome_up=%s, realized=%s, resolved_on=%s WHERE as_of=%s AND subject=%s AND horizon_days=%s AND outcome_up IS NULL",
                (bool(up), r, data.dates[i + h], as_of, subject, h),
            )
            n += 1
    return n


def track_record(
    conn: psycopg.Connection,
    subject: str,
    horizon: int,
    live: bool,
    since: date | None = None,
    product: str | None = None,
) -> predict.Skill | None:
    """How a product (both when None) did on its resolved predictions against the plain base rate."""
    rows = conn.execute(
        "SELECT p_up, outcome_up::int FROM prediction_log WHERE subject=%s AND horizon_days=%s AND live=%s AND outcome_up IS NOT NULL AND as_of >= coalesce(%s, 'epoch'::date)"
        " AND (%s::text IS NULL OR model_version=%s)",
        (subject, horizon, live, since, product, None if product is None else version(product)),
    ).fetchall()
    if not rows:
        return None
    a = np.array(rows, dtype=float)
    return predict.skill(a[:, 0], a[:, 1])


_ = json
