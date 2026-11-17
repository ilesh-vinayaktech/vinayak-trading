# ruff: noqa: E501
"""Support, resistance, breakouts and histograms for one stock from its daily bars (TODO 6.6). Pure: lists in, numbers out; floats on purpose (these are
levels to look at, not money).

Levels: swing pivots (a high, or a low, that is the extreme of the `k` bars either side, so a pivot is only known `k` bars after it, never earlier), pivot prices
within TOL of each other merged into one level with its number of touches. Highs and lows are pooled on purpose: a broken resistance turns into support. Levels
below the last close are supports, above are resistances. Volume at price: each bar's volume spread evenly over the price bins its low-to-high range covers, over
the last PROFILE_DAYS; the point of control is the busiest bin and the value area the narrowest run around it holding 70% of the volume. Status compares the last close
with the levels known BEFORE that bar: a close more than BREAK_MARGIN beyond the nearest resistance (support) after a close inside is a breakout (breakdown), 'confirmed' when
the day's volume is at least 1.5x its norm and, where given, delivery % is at least 1.2x its norm. Cutting the bars off at a day gives that day's answer unchanged."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

PIVOT_K = 5
TOL = 0.015  # pivot prices within 1.5% of the level's average are one level
NEAR = 0.015  # within 1.5% below a resistance (above a support) counts as testing it
BREAK_MARGIN = 0.005
PROFILE_DAYS, BINS, VALUE_AREA = 120, 24, 0.70
MIN_BARS = 60


@dataclass(frozen=True)
class Level:
    price: float
    touches: int
    bars_since: int  # bars since the latest touch
    distance_pct: float  # from the last close, negative below


def swing_points(
    high: Sequence[float], low: Sequence[float], k: int = PIVOT_K
) -> list[tuple[int, float]]:
    """(index, price) of every swing high and swing low that has k bars after it."""
    out: list[tuple[int, float]] = []
    for i in range(k, len(high) - k):
        if high[i] > max(high[i - k : i]) and high[i] >= max(high[i + 1 : i + k + 1]):
            out.append((i, high[i]))
        if low[i] < min(low[i - k : i]) and low[i] <= min(low[i + 1 : i + k + 1]):
            out.append((i, low[i]))
    return out


def clusters(points: Sequence[tuple[int, float]], last: int, close: float) -> list[Level]:
    groups: list[list[tuple[int, float]]] = []
    for pt in sorted(points, key=lambda p: p[1]):
        if groups and pt[1] <= np.mean([p[1] for p in groups[-1]]) * (1 + TOL):
            groups[-1].append(pt)
        else:
            groups.append([pt])
    return [
        Level(
            float(np.mean([p[1] for p in g])),
            len(g),
            last - max(p[0] for p in g),
            100 * (float(np.mean([p[1] for p in g])) / close - 1),
        )
        for g in groups
    ]


def nearest(levels: Sequence[Level], close: float) -> tuple[list[Level], list[Level]]:
    """(supports, resistances): below and above the close, closest first."""
    below = sorted((lv for lv in levels if lv.price < close), key=lambda lv: -lv.price)
    above = sorted((lv for lv in levels if lv.price > close), key=lambda lv: lv.price)
    return below, above


def volume_profile(
    high: Sequence[float], low: Sequence[float], volume: Sequence[float], bins: int = BINS
) -> dict[str, object] | None:
    h, lo, v = (
        np.asarray(high[-PROFILE_DAYS:]),
        np.asarray(low[-PROFILE_DAYS:]),
        np.asarray(volume[-PROFILE_DAYS:]),
    )
    if len(h) < 20 or h.max() <= lo.min():
        return None
    edges = np.linspace(lo.min(), h.max(), bins + 1)
    vol = np.zeros(bins)
    for a, b, q in zip(lo, h, v, strict=True):
        i0 = min(int(np.searchsorted(edges, a, side="right")) - 1, bins - 1)
        i1 = min(int(np.searchsorted(edges, b, side="left")) - 1, bins - 1)
        i0, i1 = max(i0, 0), max(i1, i0)
        vol[i0 : i1 + 1] += q / (i1 - i0 + 1)
    total = vol.sum()
    if total <= 0:
        return None
    poc = int(vol.argmax())
    lo_i = hi_i = poc
    got = vol[poc]
    while got < VALUE_AREA * total and (lo_i > 0 or hi_i < bins - 1):
        up = vol[hi_i + 1] if hi_i < bins - 1 else -1.0
        dn = vol[lo_i - 1] if lo_i > 0 else -1.0
        if up >= dn:
            hi_i += 1
            got += vol[hi_i]
        else:
            lo_i -= 1
            got += vol[lo_i]
    mid = (edges[:-1] + edges[1:]) / 2
    return {
        "bins": [{"price": float(mid[i]), "share": float(vol[i] / total)} for i in range(bins)],
        "poc": float(mid[poc]), "value_low": float(edges[lo_i]), "value_high": float(edges[hi_i + 1]),
    }  # fmt: skip


def return_histogram(
    close: Sequence[float], days: int = 250, bins: int = 15
) -> dict[str, object] | None:
    c = np.asarray(close[-(days + 1) :])
    if len(c) < 30:
        return None
    r = 100 * (c[1:] / c[:-1] - 1)
    lo, hi = np.percentile(r, [1, 99])
    if hi <= lo:
        return None
    counts, edges = np.histogram(np.clip(r, lo, hi), bins=bins, range=(lo, hi))
    return {
        "bins": [{"low": float(edges[i]), "high": float(edges[i + 1]), "count": int(counts[i])} for i in range(bins)],
        "last": float(r[-1]), "last_percentile": float(100 * (r < r[-1]).mean()), "worst": float(r.min()), "best": float(r.max()),
    }  # fmt: skip


def status(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    volume: Sequence[float],
    delivery_vs_avg: float | None = None,
) -> dict[str, object]:
    """Where the last close sits against the levels known before it, and whether it broke one."""
    n = len(close)
    prior = n - 1
    sup, res = nearest(
        clusters(swing_points(high[:prior], low[:prior]), prior - 1, close[prior - 1]),
        close[prior - 1],
    )
    last, prev = close[-1], close[-2]
    avg_vol = float(np.mean(volume[-21:-1])) if n > 21 else 0.0
    vol_ratio = volume[-1] / avg_vol if avg_vol > 0 else None
    confirmed = (
        vol_ratio is not None
        and vol_ratio >= 1.5
        and (delivery_vs_avg is None or delivery_vs_avg >= 1.2)
    )
    state, level = "Inside its range", None
    if (
        res
        and last > res[0].price * (1 + BREAK_MARGIN)
        and prev <= res[0].price * (1 + BREAK_MARGIN)
    ):
        state, level = ("Breakout" if confirmed else "Breakout, weak volume"), res[0].price
    elif (
        sup
        and last < sup[0].price * (1 - BREAK_MARGIN)
        and prev >= sup[0].price * (1 - BREAK_MARGIN)
    ):
        state, level = ("Breakdown" if confirmed else "Breakdown, weak volume"), sup[0].price
    elif res and last >= res[0].price * (1 - NEAR) and last <= res[0].price * (1 + BREAK_MARGIN):
        state, level = "Testing resistance", res[0].price
    elif sup and last <= sup[0].price * (1 + NEAR) and last >= sup[0].price * (1 - BREAK_MARGIN):
        state, level = "Testing support", sup[0].price
    return {
        "state": state,
        "level": level,
        "volume_ratio": vol_ratio,
        "delivery_vs_avg": delivery_vs_avg,
    }


def analyse(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    volume: Sequence[float],
    delivery_vs_avg: float | None = None,
) -> dict[str, object] | None:
    """Everything for one stock, or None with fewer than MIN_BARS bars."""
    n = len(close)
    if n < MIN_BARS or not (n == len(high) == len(low) == len(volume)):
        return None
    last = close[-1]
    sup, res = nearest(clusters(swing_points(high, low), n - 1, last), last)
    year = close[-252:]
    return {
        "price": last,
        "supports": [lv.__dict__ for lv in sup[:4]],
        "resistances": [lv.__dict__ for lv in res[:4]],
        "status": status(high, low, close, volume, delivery_vs_avg),
        "profile": volume_profile(high, low, volume),
        "returns": return_histogram(close),
        "high_52w": max(year), "low_52w": min(year),
    }  # fmt: skip
