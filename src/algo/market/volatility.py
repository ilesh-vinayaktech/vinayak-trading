# ruff: noqa: E501
"""How big will the next session's move be? (forecast plan step 2: a volatility forecast, separate from the direction forecast.) Targets, both for the Nifty 500:
the next session's high-low range as % of its open (primary) and its absolute close-to-close move in % (secondary). Both are positive and skewed, so the model works on logs.
Model: ridge regression on a handful of inputs known before the open, in the spirit of the HAR model (yesterday, the last week and the last month of ranges) plus India VIX
and the US overnight (the S&P's size of move, the US VIX change). Walk-forward like the direction forecast: refitted every 21 sessions, only on sessions whose outcome was already known.
Pure functions on arrays; statistics, so floats."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
from numpy.typing import NDArray

Arr = NDArray[np.float64]
ALPHA = 10.0  # ridge strength, fixed in advance
MIN_TRAIN = 500
REFIT = 21
FEATURES = (
    "range_yesterday",
    "range_week",
    "range_month",
    "move_week",
    "india_vix",
    "us_sp_size",
    "us_vix_change",
)
FLOOR = 0.05  # added before taking logs of an absolute move, so a flat day does not send the log to minus infinity


@dataclass(frozen=True)
class Session:
    day: date
    open: float
    high: float
    low: float
    close: float


def range_pct(s: Session) -> float:
    """High to low as a % of the open."""
    return 100.0 * (s.high - s.low) / s.open


def move_pct(prev_close: float, s: Session) -> float:
    """Absolute close-to-close move in %."""
    return abs(100.0 * (s.close / prev_close - 1))


def _inputs(rng: Arr, mov: Arr, i: int, vix_prev: float, night: tuple[float, float]) -> list[float]:
    """The seven inputs for the session at position i, from sessions before it, the previous close of India VIX and the US overnight (S&P % move, US VIX % change)."""
    us_sp, us_vix = night
    return [
        float(np.log(rng[i - 1])), float(np.mean(np.log(rng[i - 5 : i]))), float(np.mean(np.log(rng[i - 22 : i]))), float(np.log(np.mean(mov[i - 5 : i]) + FLOOR)),
        float(np.log(vix_prev)), float(np.log(abs(us_sp) + FLOOR)), float(us_vix),
    ]  # fmt: skip


def _series(sessions: Sequence[Session]) -> tuple[Arr, Arr]:
    rng = np.array([range_pct(s) for s in sessions])
    mov = np.array(
        [np.nan] + [move_pct(a.close, b) for a, b in zip(sessions, sessions[1:], strict=False)]
    )
    return rng, mov


def next_row(
    sessions: Sequence[Session], vix: dict[date, float], night: tuple[float, float] | None
) -> Arr | None:
    """The inputs for the session AFTER the last one given (the forecast session), or None without 23 sessions, the last session's India VIX close, or the US overnight figures."""
    if len(sessions) < 23 or sessions[-1].day not in vix or night is None:
        return None
    rng, mov = _series(sessions)
    return np.array(_inputs(rng, mov, len(sessions), vix[sessions[-1].day], night))


def block_start(position: int) -> int | None:
    """Where the training rows end for the forecast at row `position`: the walk-forward refit rule (a fit every REFIT rows after the first MIN_TRAIN), so every forecast inside a block
    shares one fit. None while there are fewer than MIN_TRAIN rows."""
    return None if position < MIN_TRAIN else MIN_TRAIN + REFIT * ((position - MIN_TRAIN) // REFIT)


def forecast_next(x_hist: Arr, y_hist: Arr, x_next: Arr) -> tuple[float, int] | None:
    """The expected range for the row that would come after `x_hist`, and how many rows it learned from: exactly what `walk_forward` gives that row, so a live forecast can be rebuilt from the data."""
    start = block_start(len(y_hist))
    if start is None:
        return None
    return float(
        predict(fit_ridge(x_hist[:start], y_hist[:start]), x_next.reshape(1, -1))[0]
    ), start


def build(
    sessions: Sequence[Session], vix: dict[date, float], overnight: dict[date, tuple[float, float]]
) -> tuple[list[date], Arr, Arr, Arr]:
    """For every session from the 23rd on: (its date, the inputs known before its open, its high-low range, its absolute move). `vix` is India VIX by day (previous close is used);
    `overnight` maps a session date to (the S&P 500's % move, the US VIX's % change) in the last US session before it; a session without either is skipped."""
    rng, mov = _series(sessions)
    days, xs, yr, ym = [], [], [], []
    for i in range(23, len(sessions)):
        d, prev = sessions[i].day, sessions[i - 1].day
        if prev not in vix or d not in overnight:
            continue
        xs.append(_inputs(rng, mov, i, vix[prev], overnight[d]))
        days.append(d)
        yr.append(rng[i])
        ym.append(mov[i])
    return days, np.array(xs), np.array(yr), np.array(ym)


def fit_ridge(x: Arr, y: Arr) -> tuple[Arr, Arr, Arr, float, float]:
    """Standardise on the training rows and fit the ridge; returns (mean, scale, coef, intercept, smearing). Predictions are made in logs; `smearing` (the average of exp of the
    training residuals) turns them back into levels without the bias a plain exp has."""
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale = np.where(scale < 1e-12, 1.0, scale)
    z = (x - mean) / scale
    ly = np.log(y + (FLOOR if y.min() <= 0 else 0.0))
    ybar = ly.mean()
    coef = np.linalg.solve(z.T @ z + ALPHA * np.eye(z.shape[1]), z.T @ (ly - ybar))
    smear = float(np.mean(np.exp(ly - ybar - z @ coef)))
    return mean, scale, coef, float(ybar), smear


def predict(model: tuple[Arr, Arr, Arr, float, float], x: Arr) -> Arr:
    mean, scale, coef, ybar, smear = model
    return np.asarray(np.exp(ybar + ((x - mean) / scale) @ coef) * smear)


def walk_forward(x: Arr, y: Arr) -> Arr:
    """Out-of-sample predictions in levels from the MIN_TRAIN-th session on (NaN before): each block of REFIT sessions is predicted by a model fitted only on the sessions before it."""
    out = np.full(len(y), np.nan)
    for start in range(MIN_TRAIN, len(y), REFIT):
        end = min(start + REFIT, len(y))
        out[start:end] = predict(fit_ridge(x[:start], y[:start]), x[start:end])
    return out


def persistence(y: Arr) -> Arr:
    """Yesterday's value is tomorrow's forecast."""
    return np.concatenate([[np.nan], y[:-1]])


def trailing_mean(y: Arr, n: int) -> Arr:
    """The mean of the last n sessions' values."""
    return np.array([np.nan] * n + [float(np.mean(y[i - n : i])) for i in range(n, len(y))])


def scaled_vix(x: Arr, y: Arr, vix_col: int = 4) -> Arr:
    """India VIX turned into a forecast of the target by one multiplier fitted (through the origin) on the sessions before each block, refitted like the model."""
    vix = np.exp(x[:, vix_col])
    out = np.full(len(y), np.nan)
    for start in range(MIN_TRAIN, len(y), REFIT):
        end = min(start + REFIT, len(y))
        k = float(np.sum(vix[:start] * y[:start]) / np.sum(vix[:start] ** 2))
        out[start:end] = k * vix[start:end]
    return out


def errors(pred: Arr, y: Arr) -> tuple[float, float]:
    """(mean absolute error, root mean squared error) in the target's own units (% points)."""
    e = pred - y
    return float(np.mean(np.abs(e))), float(np.sqrt(np.mean(e**2)))


def change_direction_accuracy(pred: Arr, y: Arr, yesterday: Arr) -> float:
    """How often the forecast got the direction of the change right: higher or lower than yesterday's actual value."""
    return float(np.mean((pred > yesterday) == (y > yesterday)))
