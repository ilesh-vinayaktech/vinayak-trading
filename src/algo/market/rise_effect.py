# ruff: noqa: E501
"""What a stock's own rise-odds history says about its price: each scored day's chance, set against the stock's real return over the next HORIZON sessions.

Bands are the stock's OWN scores: the top fifth, the middle three fifths and the bottom fifth of its scored days, so a stock whose score barely moves is still split fairly. Only days with all HORIZON following
sessions are counted. A stock has a few hundred scored days at most, so every figure is a description of that one stock, never a forecast (scripts/study_learned_signals.py: the model's edge is a few tenths of a percent)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

HORIZON = 5
MIN_DAYS = 30  # fewer matched days than this: nothing is said


def _stats(returns: Sequence[float]) -> dict[str, Any]:
    n = len(returns)
    if n == 0:
        return {"n": 0, "mean": None, "up_share": None}
    return {
        "n": n,
        "mean": round(100 * sum(returns) / n, 2),
        "up_share": round(100 * sum(r > 0 for r in returns) / n, 1),
    }


def _rank_corr(a: Sequence[float], b: Sequence[float]) -> float | None:
    """Spearman correlation (ties get the average rank); None when either side is constant."""

    def ranks(x: Sequence[float]) -> list[float]:
        order = sorted(range(len(x)), key=lambda i: x[i])
        out, i = [0.0] * len(x), 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and x[order[j + 1]] == x[order[i]]:
                j += 1
            for k in range(i, j + 1):
                out[order[k]] = (i + j) / 2
            i = j + 1
        return out

    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    va, vb = sum((x - ma) ** 2 for x in ra), sum((y - mb) ** 2 for y in rb)
    if va == 0 or vb == 0:
        return None
    return round(
        float(sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True)) / (va * vb) ** 0.5), 3
    )


def effect(
    scores: Sequence[tuple[date, float]], closes: Sequence[tuple[date, float]]
) -> dict[str, Any]:
    """`scores`: (day, chance) oldest first; `closes`: the stock's (day, close) oldest first. Returns the bands and the rank correlation, or `enough: False`."""
    index = {d: i for i, (d, _) in enumerate(closes)}
    pairs = [
        (p, closes[i + HORIZON][1] / closes[i][1] - 1)
        for d, p in scores
        if (i := index.get(d)) is not None and i + HORIZON < len(closes) and closes[i][1] > 0
    ]
    if len(pairs) < MIN_DAYS:
        return {
            "horizon": HORIZON,
            "enough": False,
            "days": len(pairs),
            "all": _stats([r for _, r in pairs]),
            "bands": [],
            "rank_correlation": None,
        }
    ordered = sorted(pairs, key=lambda x: x[0])
    k = len(ordered) // 5
    low, mid, high = ordered[:k], ordered[k : len(ordered) - k], ordered[len(ordered) - k :]
    bands = [
        {
            "band": name,
            "from": round(grp[0][0], 4),
            "to": round(grp[-1][0], 4),
            **_stats([r for _, r in grp]),
        }
        for name, grp in (("top fifth", high), ("middle", mid), ("bottom fifth", low))
    ]
    return {
        "horizon": HORIZON, "enough": True, "days": len(pairs), "all": _stats([r for _, r in pairs]), "bands": bands,
        "rank_correlation": _rank_corr([p for p, _ in pairs], [r for _, r in pairs]),
    }  # fmt: skip
