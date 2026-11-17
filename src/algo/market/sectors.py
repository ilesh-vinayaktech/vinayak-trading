# ruff: noqa: E501
"""Sector rotation (TODO 6.4): where money is flowing, from the NSE sector and theme indices against a broad benchmark (Nifty 500).

For each sector index: returns over 1, 5, 21, 63 and 252 trading days, whether it is above its 50 and 200-day average, and its relative strength
RS = sector / benchmark. `rs_ratio` is RS against its own 50-day average (above 100 = outperforming its recent norm) and `rs_momentum` is that ratio against
the ratio 10 days ago (above 100 = outperformance improving). Together they give the four rotation quadrants: Leading (ahead and improving or steady),
Weakening (ahead but fading), Lagging (behind and not improving) and Improving (behind but turning up). `score` is the mean of the sector's percentile rank,
across the sectors given, on 21-day return, 63-day return and rs_ratio (0 to 100). Point in time: the row for day `at` uses only days up to `at`. Statistics, not
money: floats on purpose."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

import psycopg

from algo.market.zone import pct_rank

RS_AVG, MOM_GAP, FLAT = (
    50,
    10,
    0.1,
)  # FLAT: momentum within 0.1 of 100 means the ratio moved under 0.1% in 10 days: steady, not turning
BENCHMARK = "NIFTY 500"
SECTORS = {  # index symbol -> name shown
    "NIFTY BANK": "Bank",
    "NIFTY PVT BANK": "Private bank",
    "NIFTY PSU BANK": "PSU bank",
    "NIFTY FIN SERVICE": "Financial services",
    "NIFTY IT": "IT",
    "NIFTY PHARMA": "Pharma",
    "NIFTY HEALTHCARE": "Healthcare",
    "NIFTY AUTO": "Auto",
    "NIFTY FMCG": "FMCG",
    "NIFTY CONSUMPTION": "Consumption",
    "NIFTY CONSR DURBL": "Consumer durables",
    "NIFTY METAL": "Metal",
    "NIFTY REALTY": "Realty",
    "NIFTY ENERGY": "Energy",
    "NIFTY OIL AND GAS": "Oil and gas",
    "NIFTY INFRA": "Infrastructure",
    "NIFTY MEDIA": "Media",
    "NIFTY PSE": "PSU enterprises",
    "NIFTY COMMODITIES": "Commodities",
    "NIFTY INDIA MFG": "Manufacturing",
    "NIFTY MNC": "MNC",
}


@dataclass(frozen=True)
class SectorRow:
    name: str
    close: float
    ret_1d: float | None
    ret_5d: float | None
    ret_21d: float | None
    ret_63d: float | None
    ret_252d: float | None
    above_50: bool
    above_200: bool
    rs_ratio: float
    rs_momentum: float
    quadrant: str
    score: float


def quadrant(rs_ratio: float, rs_momentum: float) -> str:
    """Steady counts as holding: a sector that outperforms at a constant rate has a flat ratio, and must not flip on rounding noise (index closes are
    stored to 4 decimals, so momentum within FLAT of 100 is flat)."""
    if rs_ratio > 100:
        return "Leading" if rs_momentum >= 100 - FLAT else "Weakening"
    return "Improving" if rs_momentum > 100 + FLAT else "Lagging"


def _ret(xs: Sequence[float], n: int, i: int) -> float | None:
    return xs[i] / xs[i - n] - 1 if i >= n and xs[i - n] != 0 else None


def _sma(xs: Sequence[float], n: int, i: int) -> float:
    return sum(xs[i - n + 1 : i + 1]) / n


def _ratio(sector: Sequence[float], bench: Sequence[float], i: int) -> float:
    rs = [sector[j] / bench[j] for j in range(i - RS_AVG + 1, i + 1)]
    return 100.0 * rs[-1] / (sum(rs) / len(rs))


def rotation(
    series: Mapping[str, Sequence[float]], bench: Sequence[float], at: int | None = None
) -> list[SectorRow]:
    """One row per sector that has enough history on day `at` (default the last): at least 200 days, and as long as the benchmark. Others are left out."""
    i = len(bench) - 1 if at is None else at
    if i < 199 or i >= len(bench):
        return []
    raw: list[tuple[str, Sequence[float], float, float]] = []
    for name, s in series.items():
        if len(s) <= i:
            continue
        ratio, before = _ratio(s, bench, i), _ratio(s, bench, i - MOM_GAP)
        raw.append((name, s, ratio, 100.0 * ratio / before))
    if not raw:
        return []
    r21 = [_ret(s, 21, i) or 0.0 for _, s, _, _ in raw]
    r63 = [_ret(s, 63, i) or 0.0 for _, s, _, _ in raw]
    ratios = [ratio for _, _, ratio, _ in raw]
    rows = []
    for k, (name, s, ratio, mom) in enumerate(raw):
        score = (pct_rank(r21, r21[k]) + pct_rank(r63, r63[k]) + pct_rank(ratios, ratio)) / 3
        rows.append(
            SectorRow(
                name=name,
                close=s[i],
                ret_1d=_ret(s, 1, i),
                ret_5d=_ret(s, 5, i),
                ret_21d=_ret(s, 21, i),
                ret_63d=_ret(s, 63, i),
                ret_252d=_ret(s, 252, i),
                above_50=s[i] > _sma(s, 50, i),
                above_200=s[i] > _sma(s, 200, i),
                rs_ratio=ratio,
                rs_momentum=mom,
                quadrant=quadrant(ratio, mom),
                score=score,
            )
        )
    return rows


def load(
    conn: psycopg.Connection, days: int = 420
) -> tuple[list[date], list[float], dict[str, list[float]]]:
    """The benchmark's last `days` trading days and each sector index on the same days (a day an index did not print carries its last close; an index that
    starts after the first day is left out)."""
    bench_rows = conn.execute(
        "SELECT trade_date, close FROM index_bar_1d WHERE exchange='NSE' AND symbol=%s ORDER BY trade_date DESC LIMIT %s",
        (BENCHMARK, days),
    ).fetchall()[::-1]
    if not bench_rows:
        return [], [], {}
    dates = [r[0] for r in bench_rows]
    out: dict[str, list[float]] = {}
    for symbol, name in SECTORS.items():
        rows = conn.execute(
            "SELECT trade_date, close FROM index_bar_1d WHERE exchange='NSE' AND symbol=%s AND trade_date <= %s ORDER BY trade_date",
            (symbol, dates[-1]),
        ).fetchall()
        if not rows or rows[0][0] > dates[0]:
            continue
        k, last, series = 0, float(rows[0][1]), []
        for d in dates:
            while k < len(rows) and rows[k][0] <= d:
                last = float(rows[k][1])
                k += 1
            series.append(last)
        out[name] = series
    return dates, [float(r[1]) for r in bench_rows], out
