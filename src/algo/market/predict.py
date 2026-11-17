# ruff: noqa: E501
"""Will the market, or a sector, close higher? (TODO 6.5.) A regularised logistic model per horizon, on evidence we already compute, learning from every outcome.

Evidence for the market on day t: the eight zone signals (0-100, as stored), the fear/greed score, the index's 1, 5 and 21-day returns and the share of stocks that rose.
For a sector: its own 1, 5 and 21-day returns, relative strength against its norm and its momentum, its rotation score, above the 50 and 200-day average, plus the market's
fear/greed and 1-day return; ONE model is shared by all sectors. A signal that is missing counts as neutral, never as extreme.
Learning is walk-forward: the model for day t is fitted only on days whose outcome was already known on t (a row at j has its outcome at j + horizon, so j + horizon <= t),
refitted every REFIT days, never on data it is scored on. `walk_forward` gives those honest predictions, `fit` the model for tomorrow, and `skill` scores any set of
predictions against the plain base rate (always say 'up' as often as it has been), so a model that does not beat guessing is shown as exactly that. Statistics, not money: floats."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]

Arr = NDArray[np.float64]
MODEL_VERSION = "logit-v1"
MIN_TRAIN = 500  # rows before the first walk-forward prediction
REFIT = 21  # trading days between refits
C = 0.05  # strong regularisation: a day's direction is mostly noise, so the model must not chase it
LABELS = {
    "momentum": "Index momentum", "breadth": "Stocks above their averages", "highs_lows": "New highs against new lows",
    "volatility": "Volatility", "advance_decline": "Advancing against declining stocks", "stocks_vs_bonds": "Stocks against bonds",
    "risk_appetite": "Appetite for high-beta stocks", "size_appetite": "Appetite for small caps", "fear_greed": "Fear/greed score",
    "ret_1d": "Last day's move", "ret_5d": "5-day move", "ret_21d": "21-day move", "adv_share": "Share of stocks that rose",
    "rs_ratio": "Strength against the market", "rs_momentum": "Strength improving", "rotation": "Sector rotation score",
    "above_50": "Above its 50-day average", "above_200": "Above its 200-day average", "mkt_fear_greed": "Market fear/greed", "mkt_ret_1d": "Market's last move",
}  # fmt: skip


@dataclass(frozen=True)
class Model:
    names: tuple[str, ...]
    mean: Arr
    scale: Arr
    coef: Arr
    intercept: float

    def p_up(self, x: Arr) -> Arr:
        z = ((np.atleast_2d(x) - self.mean) / self.scale) @ self.coef + self.intercept
        return np.asarray(1.0 / (1.0 + np.exp(-z)))

    def evidence(self, x: Arr, top: int = 3) -> list[dict[str, object]]:
        """The features that pushed this row's probability furthest from the model's average, as [{feature, value, effect}] (effect in log-odds)."""
        push = ((np.asarray(x) - self.mean) / self.scale) * self.coef
        order = np.argsort(-np.abs(push))[:top]
        return [
            {
                "feature": self.names[i],
                "value": round(float(x[i]), 3),
                "effect": round(float(push[i]), 3),
            }
            for i in order
            if abs(push[i]) > 1e-9
        ]


def fit(x: Arr, y: Arr, names: Sequence[str]) -> Model | None:
    """None when the outcomes are all one value (nothing to learn)."""
    if len(x) == 0 or len(set(y.tolist())) < 2:
        return None
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale = np.where(scale < 1e-12, 1.0, scale)
    lr = LogisticRegression(C=C, max_iter=500).fit((x - mean) / scale, y)
    return Model(tuple(names), mean, scale, lr.coef_[0], float(lr.intercept_[0]))


def walk_forward(x: Arr, y: Arr, day: Arr, horizon: int, names: Sequence[str]) -> tuple[Arr, Arr]:
    """Out-of-sample probabilities for every row from the MIN_TRAIN-th day on. Rows are sorted by `day` (an int position, repeats allowed for pooled
    subjects); `y` is NaN where the outcome is not known yet. Returns (p, mask) with mask True where p was made."""
    p = np.full(len(x), np.nan)
    days = np.unique(day)
    for start in range(MIN_TRAIN, len(days), REFIT):
        t = days[start]
        train = (day + horizon <= t) & ~np.isnan(y)
        model = fit(x[train], y[train], names)
        if model is None:
            continue
        end = days[min(start + REFIT, len(days)) - 1]
        rows = (day >= t) & (day <= end)
        p[rows] = model.p_up(x[rows])
    return p, ~np.isnan(p)


@dataclass(frozen=True)
class Skill:
    n: int
    hit_rate: float  # share of calls (p above 0.5 = up) that were right
    base_rate: float  # share of outcomes that were up
    base_hit: float  # hit rate of always saying the more common direction
    brier: float
    brier_base: float  # Brier score of always saying the base rate
    brier_skill: float  # 1 - brier / brier_base: above 0 beats the base rate, 0 or below does not
    calibration: list[
        tuple[float, float, int]
    ]  # (average predicted, share that went up, n) per bin


def skill(p: Arr, up: Arr, bins: int = 5) -> Skill | None:
    if len(p) == 0:
        return None
    base = float(up.mean())
    brier, brier_base = float(np.mean((p - up) ** 2)), float(np.mean((base - up) ** 2))
    edges = np.quantile(p, np.linspace(0, 1, bins + 1))
    which = np.clip(np.searchsorted(edges[1:-1], p, side="right"), 0, bins - 1)
    cal = [
        (float(p[which == b].mean()), float(up[which == b].mean()), int((which == b).sum()))
        for b in range(bins)
        if (which == b).any()
    ]
    return Skill(
        len(p),
        float(np.mean((p > 0.5) == (up > 0.5))),
        base,
        max(base, 1 - base),
        brier,
        brier_base,
        1 - brier / brier_base if brier_base > 0 else 0.0,
        cal,
    )
