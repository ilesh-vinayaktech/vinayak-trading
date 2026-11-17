# ruff: noqa: E501
"""The forecast job (TODO 6.5): build the evidence from the stored zone and the index series, make the predictions of algo.market.predict, log them in
`prediction_log`, and resolve earlier ones once their horizon has passed. `backfill` writes the walk-forward history (each day predicted by a model fitted only on
outcomes known by then); `tonight` makes the live predictions for the latest trading day (the model fitted on every resolved outcome) and resolves what is due."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

import numpy as np
import psycopg
from psycopg.types.json import Jsonb

from algo.market import predict, sectors
from algo.market.predict import Arr
from algo.market.zone import SIGNALS

Table = tuple[Arr, Arr, Arr, Arr, list[str], list[str]]
HORIZONS = (1, 5)
MARKET = "MARKET"
DAYS = 2200  # about 8.5 years of index history: sectors whose index starts later than this are left out
M_NAMES = (*SIGNALS, "fear_greed", "ret_1d", "ret_5d", "ret_21d", "adv_share")
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
)


@dataclass
class Data:
    dates: list[date]
    series: dict[str, list[float]]  # MARKET and every sector: one close per date
    market_x: dict[int, list[float]]  # position -> features
    sector_x: dict[int, dict[str, list[float]]]


def _pct(xs: list[float], i: int, n: int) -> float:
    return 100.0 * (xs[i] / xs[i - n] - 1) if i >= n and xs[i - n] else 0.0


def load(conn: psycopg.Connection) -> Data:
    dates, bench, sec = sectors.load(conn, days=DAYS)
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
        fgv = 50.0 if fg is None else float(fg)
        data.market_x[i] = [
            *(50.0 if comps.get(k) is None else float(comps[k]) for k in SIGNALS),
            fgv, _pct(bench, i, 1), _pct(bench, i, 5), _pct(bench, i, 21), 100.0 * adv / (adv + dec) if adv + dec else 50.0,
        ]  # fmt: skip
        if i >= 199:
            data.sector_x[i] = {
                r.name: [
                    100 * (r.ret_1d or 0.0), 100 * (r.ret_5d or 0.0), 100 * (r.ret_21d or 0.0), r.rs_ratio - 100, r.rs_momentum - 100,
                    r.score, float(r.above_50), float(r.above_200), fgv, _pct(bench, i, 1),
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


def _tables(data: Data, h: int) -> dict[str, Table]:
    """For MARKET and for the pooled sectors: features, outcome, position, return, the subject of each row and the feature names."""
    out = {}
    for kind, names in ((MARKET, M_NAMES), ("SECTORS", S_NAMES)):
        xs, ys, pos, ret, who = [], [], [], [], []
        for i in sorted(data.market_x):
            items = {MARKET: data.market_x[i]} if kind == MARKET else data.sector_x.get(i, {})
            for name, x in items.items():
                y, r = _outcome(data.series[name], i, h)
                xs.append(x)
                ys.append(y)
                pos.append(i)
                ret.append(r)
                who.append(name)  # noqa: E702
        out[kind] = (np.array(xs), np.array(ys), np.array(pos), np.array(ret), who, list(names))
    return out


def _rows(
    data: Data, h: int, live: bool, p: Arr, mask: Arr, t: Table, models: predict.Model | None = None
) -> list[tuple[object, ...]]:
    x, y, pos, ret, who, names = t
    out: list[tuple[object, ...]] = []
    for k in np.flatnonzero(mask):
        ev: list[dict[str, object]] = []
        if models is not None:
            ev = models.evidence(x[k])
        out.append((data.dates[int(pos[k])], who[k], h, predict.MODEL_VERSION, live, float(p[k]), Jsonb(ev), None if np.isnan(y[k]) else bool(y[k]), None if np.isnan(ret[k]) else float(ret[k]), None if np.isnan(y[k]) else data.dates[min(int(pos[k]) + h, len(data.dates) - 1)]))  # fmt: skip
    return out


SQL = (
    "INSERT INTO prediction_log (as_of, subject, horizon_days, model_version, live, p_up, evidence, outcome_up, realized, resolved_on) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
    " ON CONFLICT (as_of, subject, horizon_days, model_version, live) DO UPDATE SET p_up=EXCLUDED.p_up, evidence=EXCLUDED.evidence, outcome_up=EXCLUDED.outcome_up, realized=EXCLUDED.realized, resolved_on=EXCLUDED.resolved_on"
)  # fmt: skip


def backfill(conn: psycopg.Connection) -> int:
    """The walk-forward history for the market and the sectors, at every horizon. Returns rows written."""
    data = load(conn)
    n = 0
    for h in HORIZONS:
        for t in _tables(data, h).values():
            x, y, pos, _, _, names = t
            if len(x) == 0:
                continue
            p, mask = predict.walk_forward(x, y, pos, h, names)
            rows = _rows(data, h, False, p, mask, t)
            with conn.cursor() as cur:
                cur.executemany(SQL, rows)
            n += len(rows)
    return n


def tonight(conn: psycopg.Connection) -> int:
    """Live predictions for the latest day, then resolve every earlier prediction whose horizon is over. Returns rows written or resolved."""
    data = load(conn)
    if not data.market_x:
        return 0
    last = max(data.market_x)
    n = 0
    for h in HORIZONS:
        for t in _tables(data, h).values():
            x, y, pos, _, _, names = t
            known = (pos + h <= last) & ~np.isnan(y)
            model = predict.fit(x[known], y[known], names)
            today = pos == last
            if model is None or not today.any():
                continue
            p = np.full(len(x), np.nan)
            p[today] = model.p_up(x[today])
            rows = []
            for k in np.flatnonzero(today):
                rows += _rows(data, h, True, p, np.arange(len(x)) == k, t, model)
            with conn.cursor() as cur:
                cur.executemany(SQL, rows)
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
    conn: psycopg.Connection, subject: str, horizon: int, live: bool, since: date | None = None
) -> predict.Skill | None:
    rows = conn.execute(
        "SELECT p_up, outcome_up::int FROM prediction_log WHERE subject=%s AND horizon_days=%s AND live=%s AND outcome_up IS NOT NULL AND as_of >= coalesce(%s, 'epoch'::date)",
        (subject, horizon, live, since),
    ).fetchall()
    if not rows:
        return None
    a = np.array(rows, dtype=float)
    return predict.skill(a[:, 0], a[:, 1])


_ = json
