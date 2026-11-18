# ruff: noqa: E501
"""How Nifty 50 did after each zone (TODO 6.3): for every scored day, the index's return over the next 5, 20 and 60 trading days, averaged per zone and
set against the same figures for all days. Overlapping days are not independent samples, so this is a look, not a significance test. Statistics, not money."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

HORIZONS = (5, 20, 60)
ZONES = (
    ("Extreme fear", 0.0, 30.0),
    ("Fear", 30.0, 50.0),
    ("Greed", 50.0, 70.0),
    ("Extreme greed", 70.0, 101.0),
)  # the same cutoffs as zone.zone_label


@dataclass(frozen=True)
class Forward:
    horizon: int
    avg_pct: (
        float | None
    )  # mean return over the next `horizon` trading days; None with no such days
    up_pct: float | None  # share of those days that ended higher


def _forward(closes: Sequence[float], idx: Sequence[int], h: int) -> Forward:
    rets = [closes[i + h] / closes[i] - 1 for i in idx if i + h < len(closes)]
    if not rets:
        return Forward(h, None, None)
    return Forward(h, 100 * sum(rets) / len(rets), 100 * sum(r > 0 for r in rets) / len(rets))


def by_zone(
    scores: Sequence[tuple[date, float]], closes: Sequence[tuple[date, float]]
) -> list[dict[str, object]]:
    """One row per zone, then one for all days (scored period only). `closes` is oldest first; scored days with no close are skipped."""
    if not scores or not closes:
        return []
    days = [d for d, _ in closes if d >= scores[0][0]]
    px = [c for d, c in closes if d >= scores[0][0]]
    pos = {d: i for i, d in enumerate(days)}
    at = [(pos[d], v) for d, v in scores if d in pos]
    rows: list[dict[str, object]] = []
    groups = [(name, [i for i, v in at if lo <= v < hi]) for name, lo, hi in ZONES] + [
        ("All days", list(range(len(px))))
    ]
    for name, idx in groups:
        rows.append(
            {
                "zone": name,
                "days": len(idx),
                "forward": [
                    {"horizon": f.horizon, "avg_pct": f.avg_pct, "up_pct": f.up_pct}
                    for f in (_forward(px, idx, h) for h in HORIZONS)
                ],
            }
        )
    return rows


GIFT_BUCKETS = (
    ("Down more than 0.3%", -100.0, -0.3),
    ("Down up to 0.3%", -0.3, 0.0),
    ("Up up to 0.3%", 0.0, 0.3),
    ("Up more than 0.3%", 0.3, 100.0),
)


def gift_buckets(pairs: Sequence[tuple[float, float]]) -> list[dict[str, object]]:
    """From (what GIFT Nifty indicated at 08:45, in % against the last close; what the Nifty 500 then did that day, in %) per morning: how often the day closed higher
    and the average move for each size of indication."""
    rows: list[dict[str, object]] = []
    for label, lo, hi in GIFT_BUCKETS:
        day = [r for g, r in pairs if lo <= g < hi]
        rows.append(
            {
                "label": label,
                "days": len(day),
                "up_pct": 100 * sum(r > 0 for r in day) / len(day) if day else None,
                "avg_pct": sum(day) / len(day) if day else None,
            }
        )
    return rows
